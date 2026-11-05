"""Account CRUD plus upstream-health bookkeeping."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import db

STATUSES = ("active", "disabled", "invalid")


class AccountError(Exception):
    pass


class DuplicateKey(AccountError):
    pass


class NotFound(AccountError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mask(key: str) -> str:
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


def _row_dict(row: sqlite3.Row) -> dict:
    keys = row.keys()
    return {
        "id": int(row["id"]),
        "label": row["label"],
        "status": row["status"],
        "quota_limit": int(row["quota_limit"]),
        "provider_id": row["provider_id"] if "provider_id" in keys else None,
        "key_hint": _mask(row["api_key"]),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"] if "last_used_at" in keys else None,
        "last_error": row["last_error"] if "last_error" in keys else None,
        "last_error_at": row["last_error_at"] if "last_error_at" in keys else None,
        "consecutive_failures": int(row["consecutive_failures"])
        if "consecutive_failures" in keys
        else 0,
        "cooldown_until": row["cooldown_until"] if "cooldown_until" in keys else None,
        "notes": row["notes"] if "notes" in keys else None,
    }


def list_accounts() -> list[dict]:
    rows = db.connection().execute("SELECT * FROM accounts ORDER BY id").fetchall()
    return [_row_dict(row) for row in rows]


def get_account(account_id: int) -> dict:
    row = db.connection().execute(
        "SELECT * FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"account {account_id} not found")
    return _row_dict(row)


def add_account(
    api_key: str,
    *,
    label: str = "",
    quota_limit: int = 250,
    notes: str | None = None,
    provider_id: int | None = None,
) -> dict:
    api_key = (api_key or "").strip()
    if not api_key:
        raise AccountError("api_key is required")
    if quota_limit < 0:
        raise AccountError("quota_limit must be >= 0")
    label = (label or "").strip() or f"account-{_now().strftime('%H%M%S')}"
    conn = db.connection()
    if provider_id is None:
        rows = conn.execute("SELECT id, slug FROM providers ORDER BY id").fetchall()
        row = next((r for r in rows if r["slug"] == "default"), rows[0] if len(rows) == 1 else None)
        if row is None:
            raise AccountError(
                "choose a provider for this account" if rows
                else "add a provider first (Snake Charmer > Providers, or `serpent providers add`)"
            )
        provider_id = int(row["id"])
    elif conn.execute("SELECT 1 FROM providers WHERE id = ?", (provider_id,)).fetchone() is None:
        raise NotFound(f"provider {provider_id} not found")
    try:
        with db.write_tx(conn):
            cur = conn.execute(
                """
                INSERT INTO accounts (label, api_key, quota_limit, status, created_at, notes, provider_id)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (label, api_key, quota_limit, db.now_iso(), notes, provider_id),
            )
            account_id = int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise DuplicateKey("that api key is already registered") from exc
    return get_account(account_id)


def update_account(account_id: int, **changes) -> dict:
    allowed = {"label", "status", "quota_limit", "notes", "api_key", "provider_id"}
    updates = {k: v for k, v in changes.items() if k in allowed and v is not None}
    if not updates:
        raise AccountError("nothing to update")
    if "status" in updates and updates["status"] not in STATUSES:
        raise AccountError(f"status must be one of {', '.join(STATUSES)}")
    if "quota_limit" in updates and int(updates["quota_limit"]) < 0:
        raise AccountError("quota_limit must be >= 0")
    if "api_key" in updates:
        updates["api_key"] = str(updates["api_key"]).strip()

    sets = ", ".join(f"{name} = ?" for name in updates)
    values = list(updates.values()) + [account_id]
    conn = db.connection()
    try:
        with db.write_tx(conn):
            cur = conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", values)
            if cur.rowcount == 0:
                raise NotFound(f"account {account_id} not found")
            if updates.get("status") == "active":
                conn.execute(
                    "UPDATE accounts SET cooldown_until = NULL, consecutive_failures = 0 "
                    "WHERE id = ?",
                    (account_id,),
                )
    except sqlite3.IntegrityError as exc:
        raise DuplicateKey("that api key is already registered") from exc
    return get_account(account_id)


def delete_account(account_id: int) -> None:
    conn = db.connection()
    with db.write_tx(conn) as c:
        cur = c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if cur.rowcount == 0:
            raise NotFound(f"account {account_id} not found")


def seed_accounts(seed: str, default_limit: int) -> int:
    """Import ``label:key,label:key`` once.  Existing keys are skipped."""
    if not seed.strip():
        return 0
    from .config import parse_account_seed

    added = 0
    for index, (label, key) in enumerate(parse_account_seed(seed), start=1):
        exists = db.connection().execute(
            "SELECT 1 FROM accounts WHERE api_key = ?", (key,)
        ).fetchone()
        if exists:
            continue
        try:
            add_account(key, label=label or f"seed-{index}", quota_limit=default_limit)
            added += 1
        except AccountError:
            continue
    return added


# --------------------------------------------------------------------------
# health signalling
# --------------------------------------------------------------------------


def mark_success(account_id: int) -> None:
    conn = db.connection()
    with db.write_tx(conn):
        conn.execute(
            "UPDATE accounts SET consecutive_failures = 0, cooldown_until = NULL "
            "WHERE id = ?",
            (account_id,),
        )


def mark_failure(
    account_id: int,
    *,
    error: str,
    base_seconds: float = 0.0,
    max_seconds: float = 0.0,
    multiplier: float = 1.0,
) -> None:
    """Record an upstream failure and apply an exponential cooldown."""
    now = _now()
    conn = db.connection()
    with db.write_tx(conn):
        row = conn.execute(
            "SELECT consecutive_failures FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return
        failures = int(row["consecutive_failures"]) + 1
        cooldown_until = None
        if base_seconds > 0:
            seconds = base_seconds * multiplier * (2 ** min(failures - 1, 5))
            seconds = min(seconds, max_seconds) if max_seconds > 0 else seconds
            cooldown_until = (now + timedelta(seconds=seconds)).isoformat(
                timespec="seconds"
            )
        conn.execute(
            """
            UPDATE accounts
               SET consecutive_failures = ?, cooldown_until = ?,
                   last_error = ?, last_error_at = ?
             WHERE id = ?
            """,
            (
                failures,
                cooldown_until,
                error[:500],
                now.isoformat(timespec="seconds"),
                account_id,
            ),
        )


def mark_invalid(account_id: int, error: str) -> None:
    """Upstream rejected the key: disable until an operator re-enables it."""
    conn = db.connection()
    with db.write_tx(conn):
        conn.execute(
            """
            UPDATE accounts
               SET status = 'invalid', last_error = ?, last_error_at = ?,
                   consecutive_failures = consecutive_failures + 1,
                   cooldown_until = NULL
             WHERE id = ?
            """,
            (error[:500], db.now_iso(), account_id),
        )


def count_by_status() -> dict[str, int]:
    rows = db.connection().execute(
        "SELECT status, COUNT(*) AS n FROM accounts GROUP BY status"
    ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}
