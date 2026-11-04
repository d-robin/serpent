"""Quota maths, atomic reservations and rotation strategies."""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone

import pytest

from serpent import accounts, db, quota


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init_db(tmp_path / "quota.db")
    yield


def _add(label: str, key: str, limit: int) -> dict:
    return accounts.add_account(key, label=label, quota_limit=limit)


# ---------------------------------------------------------------- periods


def test_period_is_calendar_month_by_default():
    assert quota.current_period(datetime(2026, 3, 9, tzinfo=timezone.utc)) == "2026-03"
    assert quota.current_period(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)) == "2026-01"


def test_period_honours_custom_reset_day():
    march_first = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    assert quota.current_period(march_first, reset_day=15) == "2026-02"
    assert quota.current_period(datetime(2026, 3, 15, tzinfo=timezone.utc), reset_day=15) == "2026-03"


def test_period_rolls_over_in_january():
    assert quota.current_period(datetime(2026, 1, 3, tzinfo=timezone.utc), reset_day=15) == "2025-12"


def test_period_bounds_and_reset_countdown():
    start, nxt = quota.period_bounds("2026-12")
    assert start.isoformat() == "2026-12-01T00:00:00+00:00"
    assert nxt.isoformat() == "2027-01-01T00:00:00+00:00"
    assert quota.seconds_until_reset("2026-12", now=start) == 31 * 86400


# ------------------------------------------------------------- reservation


def test_reserve_stops_at_the_limit():
    _add("a", "k1", 3)
    period = "2026-01"
    for _ in range(3):
        assert quota.reserve(period=period) is not None
    assert quota.reserve(period=period) is None
    snap = quota.snapshot(period)
    assert snap["quota_used_total"] == 3
    assert snap["can_serve"] is False


def test_reserve_honours_the_reserve_floor():
    _add("a", "k1", 3)
    assert quota.reserve(period="2026-01", reserve_floor=2) is not None
    assert quota.reserve(period="2026-01", reserve_floor=2) is None


def test_refund_gives_the_credit_back():
    account = _add("a", "k1", 5)
    reservation = quota.reserve(period="2026-01")
    quota.settle_failed(reservation.account_id, "2026-01", 12.0, refund=True)
    snap = quota.snapshot("2026-01")
    assert snap["quota_used_total"] == 0
    assert snap["accounts"][0]["in_flight"] == 0
    assert snap["requests_refunded"] == 1
    assert snap["accounts"][0]["id"] == account["id"]


def test_settle_ok_consumes_and_records_latency():
    _add("a", "k1", 5)
    quota.reserve(period="2026-01")
    quota.settle_ok(1, "2026-01", 42.0)
    account = quota.snapshot("2026-01")["accounts"][0]
    assert account["used"] == 1
    assert account["ok"] == 1
    assert account["avg_latency_ms"] == 42.0
    assert account["in_flight"] == 0


def test_usage_is_per_period():
    _add("a", "k1", 2)
    quota.reserve(period="2026-01")
    quota.reserve(period="2026-01")
    assert quota.reserve(period="2026-01") is None
    # a new month starts with a fresh row
    assert quota.reserve(period="2026-02") is not None
    assert quota.snapshot("2026-02")["quota_used_total"] == 1
    assert quota.snapshot("2026-01")["quota_used_total"] == 2


def test_concurrent_reservations_never_overshoot():
    """300 callers race for 250 credits: exactly 250 must win."""
    _add("a", "k1", 250)
    period = "2026-01"
    winners = []

    def attempt(_: int) -> bool:
        return quota.reserve(period=period) is not None

    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as pool:
        for result in pool.map(attempt, range(300)):
            winners.append(result)

    assert sum(winners) == 250
    used = db.connection().execute(
        "SELECT used, in_flight FROM usage WHERE account_id = 1 AND period = ?", (period,)
    ).fetchone()
    assert used["used"] == 250
    assert used["in_flight"] == 250
    assert quota.reserve(period=period) is None


def test_rotation_balances_across_accounts():
    for index in range(3):
        _add(f"a{index}", f"k{index}", 10)
    for _ in range(9):
        quota.reserve(period="2026-01", strategy="most_remaining")
    rows = quota.accounts_snapshot("2026-01")
    assert [row["used"] for row in rows] == [3, 3, 3]


def test_round_robin_visits_each_account_in_order():
    for index in range(3):
        _add(f"a{index}", f"k{index}", 10)
    order = []
    for _ in range(6):
        reservation = quota.reserve(period="2026-01", strategy="round_robin")
        order.append(reservation.account_id)
    assert order == [1, 2, 3, 1, 2, 3]


def test_fill_first_drains_one_account_before_moving_on():
    for index in range(2):
        _add(f"a{index}", f"k{index}", 2)
    picks = [
        quota.reserve(period="2026-01", strategy="fill_first").account_id for _ in range(4)
    ]
    assert picks == [1, 1, 2, 2]


def test_excluded_accounts_are_skipped():
    _add("a", "k1", 5)
    _add("b", "k2", 5)
    first = quota.reserve(period="2026-01", strategy="fill_first")
    second = quota.reserve(period="2026-01", strategy="fill_first", exclude={first.account_id})
    assert second.account_id != first.account_id


def test_account_on_cooldown_is_not_selected():
    _add("a", "k1", 5)
    accounts.mark_failure(1, error="HTTP 500", base_seconds=60, max_seconds=120)
    assert quota.reserve(period="2026-01") is None
    snap = quota.snapshot("2026-01")
    assert snap["accounts_on_cooldown"] == 1


def test_disabled_account_is_not_selected():
    _add("a", "k1", 5)
    accounts.update_account(1, status="disabled")
    assert quota.reserve(period="2026-01") is None
    assert quota.snapshot("2026-01")["accounts_usable"] == 0


def test_reset_account_restores_full_quota():
    _add("a", "k1", 2)
    quota.reserve(period="2026-01")
    quota.reserve(period="2026-01")
    assert quota.reserve(period="2026-01") is None
    quota.reset_account(1, "2026-01")
    assert quota.reserve(period="2026-01") is not None
    snap = quota.snapshot("2026-01")
    assert snap["quota_used_total"] == 1


def test_aggregate_matches_snapshot():
    for index in range(2):
        _add(f"a{index}", f"k{index}", 4)
    quota.reserve(period="2026-01")
    agg = quota.aggregate("2026-01")
    snap = quota.snapshot("2026-01")
    for key in (
        "accounts_total",
        "accounts_usable",
        "quota_limit_total",
        "quota_used_total",
        "quota_available_total",
    ):
        assert agg[key] == snap[key]


def test_available_excludes_unusable_accounts():
    for index in range(3):
        _add(f"a{index}", f"k{index}", 10)
    accounts.update_account(2, status="invalid")
    accounts.update_account(3, status="disabled")
    snap = quota.snapshot("2026-01")
    assert snap["quota_remaining_total"] == 30      # nothing consumed
    assert snap["quota_available_total"] == 10      # only one usable account
    assert snap["accounts_usable"] == 1
    assert quota.aggregate("2026-01")["quota_available_total"] == 10


def test_available_stops_at_the_reserve_floor():
    _add("a", "k1", 5)
    assert quota.reserve(period="2026-01", reserve_floor=2) is not None
    assert quota.reserve(period="2026-01", reserve_floor=2) is not None
    assert quota.reserve(period="2026-01", reserve_floor=2) is not None
    assert quota.reserve(period="2026-01", reserve_floor=2) is None
    snap = quota.snapshot("2026-01", reserve_floor=2)
    assert snap["quota_remaining_total"] == 2
    assert snap["quota_available_total"] == 0
