"""Quota accounting: periods, reservations, settlement.

The lifecycle of one proxied request is::

    reserve()  -> a credit is held (used += 1, in_flight += 1) inside a
                  single IMMEDIATE transaction, so concurrent callers can
                  never overshoot an account's limit.
    settle_ok()      -> success, the credit is consumed.
    settle_failed(refund=True/False) -> the credit is given back or not,
                  depending on whether the provider is likely to have
                  counted it, and in_flight is released either way.

Periods are calendar months labelled ``YYYY-MM`` (or a custom reset day
within the month).  Rollover is implicit: a new period means a new row.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import db

# --------------------------------------------------------------------------
# period maths
# --------------------------------------------------------------------------


def _anchor(now: datetime, reset_day: int) -> datetime:
    """The start of the currently active quota window."""
    day = min(max(reset_day, 1), 28)
    if now.day >= day:
        start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    else:
        year, month = now.year, now.month - 1
        if month == 0:
            year, month = year - 1, 12
        start = now.replace(
            year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
        )
    return start


def current_period(now: datetime | None = None, reset_day: int = 1) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return _anchor(now.astimezone(timezone.utc), reset_day).strftime("%Y-%m")


def period_bounds(period: str, reset_day: int = 1) -> tuple[datetime, datetime]:
    """(start, next_start) for a ``YYYY-MM`` period label."""
    year, month = (int(x) for x in period.split("-"))
    day = min(max(reset_day, 1), 28)
    start = datetime(year, month, day, tzinfo=timezone.utc)
    nxt_year, nxt_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, datetime(nxt_year, nxt_month, day, tzinfo=timezone.utc)


def period_reset_at(period: str, reset_day: int = 1) -> datetime:
    return period_bounds(period, reset_day)[1]


def seconds_until_reset(period: str, reset_day: int = 1, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return max(0, int((period_reset_at(period, reset_day) - now).total_seconds()))


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

_ORDER = {
    "most_remaining": (
        "avail DESC, in_flight ASC, COALESCE(a.last_used_at, '') ASC, a.id ASC"
    ),
    "least_in_flight": (
        "in_flight ASC, avail DESC, COALESCE(a.last_used_at, '') ASC, a.id ASC"
    ),
    "least_recently_used": "COALESCE(a.last_used_at, '') ASC, a.id ASC",
    "fill_first": "a.id ASC",
    "random": "RANDOM()",
    "round_robin": "rr_next DESC, a.id ASC",
}


@dataclass(frozen=True)
class Reservation:
    account_id: int
    label: str
    api_key: str
    quota_limit: int
    used: int
    period: str

    @property
    def remaining(self) -> int:
        return max(0, self.quota_limit - self.used)


class NoCapacity(Exception):
    """No account has a usable credit right now."""


def reserve(
    *,
    period: str,
    strategy: str = "most_remaining",
    exclude: set[int] | frozenset[int] = frozenset(),
    reserve_floor: int = 0,
    now: str | None = None,
    provider_id: int | None = None,
) -> Reservation | None:
    """Atomically pick an account and hold one credit.  None = at capacity."""
    now = now or db.now_iso()
    order = _ORDER.get(strategy, _ORDER["most_remaining"])
    conn = db.connection()

    excluded = [int(i) for i in exclude]
    exclude_sql = ""
    if excluded:
        exclude_sql = "AND a.id NOT IN ({})".format(",".join("?" * len(excluded)))

    provider_sql = ""
    provider_args: tuple = ()
    if provider_id is not None:
        provider_sql = "AND a.provider_id = ?"
        provider_args = (provider_id,)

    with db.write_tx(conn):
        cursor = 0
        if strategy == "round_robin":
            cursor = int(db.get_state_in(conn, "rr_cursor", "0") or 0)

        row = conn.execute(
            f"""
            SELECT a.id, a.label, a.api_key, a.quota_limit,
                   COALESCE(u.used, 0) AS used,
                   COALESCE(u.in_flight, 0) AS in_flight,
                   (a.quota_limit - ? - COALESCE(u.used, 0)) AS avail,
                   (a.id > ?) AS rr_next
            FROM accounts a
            LEFT JOIN usage u ON u.account_id = a.id AND u.period = ?
            WHERE a.status = 'active'
              AND (a.quota_limit - ? - COALESCE(u.used, 0)) > 0
              AND (a.cooldown_until IS NULL OR a.cooldown_until <= ?)
              {exclude_sql}
              {provider_sql}
            ORDER BY {order}
            LIMIT 1
            """,
            (reserve_floor, cursor, period, reserve_floor, now, *excluded, *provider_args),
        ).fetchone()

        if row is None:
            return None

        conn.execute(
            """
            INSERT INTO usage (account_id, period, used, in_flight)
            VALUES (?, ?, 1, 1)
            ON CONFLICT(account_id, period) DO UPDATE SET
                used      = usage.used + 1,
                in_flight = usage.in_flight + 1
            """,
            (row["id"], period),
        )
        conn.execute("UPDATE accounts SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        if strategy == "round_robin":
            db.set_state_in(conn, "rr_cursor", str(row["id"]))

    return Reservation(
        account_id=int(row["id"]),
        label=row["label"],
        api_key=row["api_key"],
        quota_limit=int(row["quota_limit"]),
        used=int(row["used"]) + 1,
        period=period,
    )


# --------------------------------------------------------------------------
# settlement
# --------------------------------------------------------------------------


def _settle(
    account_id: int,
    period: str,
    *,
    refund: bool,
    ok: bool,
    latency_ms: float,
) -> None:
    """Release the in-flight slot; optionally give the credit back."""
    used_delta = -1 if refund else 0
    conn = db.connection()
    with db.write_tx(conn):
        conn.execute(
            """
            INSERT INTO usage (
                account_id, period, used, in_flight, ok, failed, refunded,
                latency_ms_sum, latency_ms_count
            ) VALUES (?, ?, MAX(0, ?), 0, ?, ?, ?, ?, 1)
            ON CONFLICT(account_id, period) DO UPDATE SET
                used             = MAX(0, usage.used + ?),
                in_flight        = MAX(0, usage.in_flight - 1),
                ok               = usage.ok + ?,
                failed           = usage.failed + ?,
                refunded         = usage.refunded + ?,
                latency_ms_sum   = usage.latency_ms_sum + ?,
                latency_ms_count = usage.latency_ms_count + 1
            """,
            (
                account_id,
                period,
                used_delta,
                int(ok),
                0 if ok else 1,
                int(refund),
                latency_ms,
                used_delta,
                int(ok),
                0 if ok else 1,
                int(refund),
                latency_ms,
            ),
        )


def settle_ok(account_id: int, period: str, latency_ms: float) -> None:
    _settle(account_id, period, refund=False, ok=True, latency_ms=latency_ms)


def settle_failed(account_id: int, period: str, latency_ms: float, *, refund: bool) -> None:
    _settle(account_id, period, refund=refund, ok=False, latency_ms=latency_ms)


def release_in_flight(account_id: int, period: str) -> None:
    """Cancelled request: drop the slot but keep the credit charged."""
    conn = db.connection()
    with db.write_tx(conn):
        conn.execute(
            "UPDATE usage SET in_flight = MAX(0, in_flight - 1) "
            "WHERE account_id = ? AND period = ?",
            (account_id, period),
        )


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def _account_rows(conn: sqlite3.Connection, period: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.id, a.label, a.status, a.quota_limit, a.created_at, a.provider_id,
               a.last_used_at, a.last_error, a.last_error_at,
               a.consecutive_failures, a.cooldown_until, a.notes,
               COALESCE(u.used, 0)             AS used,
               COALESCE(u.in_flight, 0)        AS in_flight,
               COALESCE(u.ok, 0)               AS ok,
               COALESCE(u.failed, 0)           AS failed,
               COALESCE(u.refunded, 0)         AS refunded,
               COALESCE(u.latency_ms_sum, 0)   AS latency_ms_sum,
               COALESCE(u.latency_ms_count, 0) AS latency_ms_count
        FROM accounts a
        LEFT JOIN usage u ON u.account_id = a.id AND u.period = ?
        ORDER BY a.id
        """,
        (period,),
    ).fetchall()


def _account_dict(row: sqlite3.Row, reserve_floor: int, now: datetime) -> dict:
    limit = int(row["quota_limit"])
    used = int(row["used"])
    available = max(0, limit - reserve_floor - used)
    latency_count = int(row["latency_ms_count"])
    cooldown = row["cooldown_until"]
    on_cooldown = bool(cooldown and cooldown > now.isoformat(timespec="seconds"))
    return {
        "id": int(row["id"]),
        "label": row["label"],
        "provider_id": row["provider_id"],
        "status": row["status"],
        "quota_limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "available": available,
        "reserve": reserve_floor,
        "percent_used": round(100.0 * used / limit, 1) if limit else 0.0,
        "in_flight": int(row["in_flight"]),
        "ok": int(row["ok"]),
        "failed": int(row["failed"]),
        "refunded": int(row["refunded"]),
        "avg_latency_ms": round(row["latency_ms_sum"] / latency_count, 1)
        if latency_count
        else None,
        "last_used_at": row["last_used_at"],
        "last_error": row["last_error"],
        "last_error_at": row["last_error_at"],
        "consecutive_failures": int(row["consecutive_failures"]),
        "cooldown_until": cooldown,
        "on_cooldown": on_cooldown,
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def aggregate(period: str, *, reset_day: int = 1, reserve_floor: int = 0) -> dict:
    """Cheap totals for the X-Quota-* headers and the quota API.

    Two different numbers are reported on purpose:

    ``quota_remaining_total``  credits not yet consumed (raw bookkeeping)
    ``quota_available_total``  credits you can actually spend right now:
                               only active, non-cooling accounts, above the
                               reserve floor.  This is what gates requests.
    """
    now = db.now_iso()
    # Parameter order follows the statement text: SELECT list, then the JOIN.
    row = db.connection().execute(
        """
        SELECT COUNT(*) AS accounts_total,
               COALESCE(SUM(CASE WHEN a.status = 'active' THEN 1 ELSE 0 END), 0) AS accounts_active,
               COALESCE(SUM(CASE WHEN a.status = 'active'
                                  AND (a.quota_limit - ? - COALESCE(u.used, 0)) > 0
                                  AND (a.cooldown_until IS NULL OR a.cooldown_until <= ?)
                            THEN 1 ELSE 0 END), 0) AS accounts_usable,
               COALESCE(SUM(a.quota_limit), 0)            AS quota_limit_total,
               COALESCE(SUM(COALESCE(u.used, 0)), 0)      AS quota_used_total,
               COALESCE(SUM(COALESCE(u.in_flight, 0)), 0) AS in_flight,
               COALESCE(SUM(CASE WHEN a.status = 'active'
                                  AND (a.quota_limit - ? - COALESCE(u.used, 0)) > 0
                                  AND (a.cooldown_until IS NULL OR a.cooldown_until <= ?)
                            THEN (a.quota_limit - ? - COALESCE(u.used, 0))
                            ELSE 0 END), 0) AS quota_available_total
        FROM accounts a
        LEFT JOIN usage u ON u.account_id = a.id AND u.period = ?
        """,
        (reserve_floor, now, reserve_floor, now, reserve_floor, period),
    ).fetchone()
    limit = int(row["quota_limit_total"])
    used = int(row["quota_used_total"])
    return {
        "period": period,
        "accounts_total": int(row["accounts_total"]),
        "accounts_active": int(row["accounts_active"]),
        "accounts_usable": int(row["accounts_usable"]),
        "quota_limit_total": limit,
        "quota_used_total": used,
        "quota_remaining_total": max(0, limit - used),
        "quota_available_total": max(0, int(row["quota_available_total"])),
        "in_flight": int(row["in_flight"]),
        "resets_at": period_reset_at(period, reset_day).isoformat(),
        "resets_in_seconds": seconds_until_reset(period, reset_day),
    }


def snapshot(period: str, *, reset_day: int = 1, reserve_floor: int = 0) -> dict:
    now = datetime.now(timezone.utc)
    conn = db.connection()
    rows = _account_rows(conn, period)
    accounts = [_account_dict(row, reserve_floor, now) for row in rows]

    usable = [
        a
        for a in accounts
        if a["status"] == "active" and a["available"] > 0 and not a["on_cooldown"]
    ]
    total_limit = sum(a["quota_limit"] for a in accounts)
    total_used = sum(a["used"] for a in accounts)
    return {
        "period": period,
        "resets_at": period_reset_at(period, reset_day).isoformat(),
        "resets_in_seconds": seconds_until_reset(period, reset_day, now),
        "accounts_total": len(accounts),
        "accounts_active": sum(1 for a in accounts if a["status"] == "active"),
        "accounts_usable": len(usable),
        "accounts_invalid": sum(1 for a in accounts if a["status"] == "invalid"),
        "accounts_disabled": sum(1 for a in accounts if a["status"] == "disabled"),
        "accounts_on_cooldown": sum(1 for a in accounts if a["on_cooldown"]),
        "quota_limit_total": total_limit,
        "quota_used_total": total_used,
        "quota_remaining_total": max(0, total_limit - total_used),
        # Only spendable credits: excludes disabled/invalid/cooling accounts
        # and the per-account reserve floor.  Matches quota.aggregate().
        "quota_available_total": sum(a["available"] for a in usable),
        "quota_reserve_per_account": reserve_floor,
        "requests_ok": sum(a["ok"] for a in accounts),
        "requests_failed": sum(a["failed"] for a in accounts),
        "requests_refunded": sum(a["refunded"] for a in accounts),
        "in_flight": sum(a["in_flight"] for a in accounts),
        "can_serve": bool(usable),
        "accounts": accounts,
    }


def accounts_snapshot(period: str, *, reset_day: int = 1, reserve_floor: int = 0) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        _account_dict(row, reserve_floor, now)
        for row in _account_rows(db.connection(), period)
    ]


# --------------------------------------------------------------------------
# resets
# --------------------------------------------------------------------------


def reset_account(account_id: int, period: str) -> bool:
    conn = db.connection()
    with db.write_tx(conn):
        cur = conn.execute(
            """
            INSERT INTO usage (account_id, period, used, in_flight)
            VALUES (?, ?, 0, 0)
            ON CONFLICT(account_id, period) DO UPDATE SET
                used = 0, in_flight = 0, ok = 0, failed = 0, refunded = 0,
                latency_ms_sum = 0, latency_ms_count = 0
            """,
            (account_id, period),
        )
        return cur.rowcount > 0


def reset_all(period: str) -> int:
    conn = db.connection()
    with db.write_tx(conn):
        conn.execute(
            """
            INSERT INTO usage (account_id, period, used, in_flight)
            SELECT id, ?, 0, 0 FROM accounts WHERE 1
            ON CONFLICT(account_id, period) DO UPDATE SET
                used = 0, in_flight = 0, ok = 0, failed = 0, refunded = 0,
                latency_ms_sum = 0, latency_ms_count = 0
            """,
            (period,),
        )
        conn.execute("UPDATE accounts SET cooldown_until = NULL, consecutive_failures = 0")
        row = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()
        return int(row["n"])


def purge_old_periods(keep_periods: int = 6) -> int:
    """Keep the quota table small; the Pi's SD card will thank you."""
    conn = db.connection()
    with db.write_tx(conn):
        cur = conn.execute(
            """
            DELETE FROM usage WHERE period NOT IN (
                SELECT DISTINCT period FROM usage ORDER BY period DESC LIMIT ?
            )
            """,
            (keep_periods,),
        )
        return cur.rowcount


def period_started_at(period: str, reset_day: int = 1) -> datetime:
    return period_bounds(period, reset_day)[0]


def next_reset_delta(period: str, reset_day: int = 1) -> timedelta:
    return period_reset_at(period, reset_day) - datetime.now(timezone.utc)
