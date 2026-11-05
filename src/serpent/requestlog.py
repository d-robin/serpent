"""Recent-request ring buffer, persisted so the dashboard survives restarts."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from . import db

_SECRET_PARAM = re.compile(r"key|token|secret|auth|pass|sig", re.IGNORECASE)


def logged_path(path: str, query_items) -> str:
    """``path`` plus its query string, minus anything that looks like a credential."""
    kept = [(k, v) for k, v in query_items if not _SECRET_PARAM.search(k)]
    return f"{path}?{urlencode(kept)}" if kept else path


def record(
    *,
    account_id: int | None,
    account: str | None,
    client: str,
    method: str,
    path: str,
    status: int,
    latency_ms: float,
    cached: bool = False,
    error: str | None = None,
    provider: str | None = None,
    keep: int = 500,
) -> None:
    if keep <= 0:
        return
    conn = db.connection()
    with db.write_tx(conn):
        conn.execute(
            """
            INSERT INTO request_log
                (ts, account_id, account, client, method, path, status, latency_ms, cached, error, provider_slug)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                db.now_iso(),
                account_id,
                account,
                client,
                method,
                path[:300],
                status,
                round(latency_ms, 1),
                int(cached),
                (error or None) and error[:300],
                provider,
            ),
        )
        conn.execute(
            """
            DELETE FROM request_log
             WHERE id <= (SELECT MAX(id) FROM request_log) - ?
            """,
            (keep,),
        )


def recent(limit: int = 50) -> list[dict]:
    rows = db.connection().execute(
        """
        SELECT id, ts, account_id, account, client, method, path, status,
               latency_ms, cached, error, provider_slug
          FROM request_log
         ORDER BY id DESC
         LIMIT ?
        """,
        (max(1, min(limit, 500)),),
    ).fetchall()
    return [dict(row) for row in rows]


def search(
    *,
    limit: int = 50,
    offset: int = 0,
    outcome: str = "",
    provider: str = "",
    text: str = "",
) -> dict:
    """Page through the log. ``outcome``: "ok" (<400), "failed" (>=400) or "" for all."""
    where, args = [], []
    if outcome == "ok":
        where.append("status < 400")
    elif outcome == "failed":
        where.append("status >= 400")
    if provider:
        where.append("provider_slug = ?")
        args.append(provider)
    if text:
        esc = text.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        like = f"%{esc}%"
        where.append("(path LIKE ? ESCAPE '!' OR account LIKE ? ESCAPE '!' OR error LIKE ? ESCAPE '!')")
        args += [like, like, like]
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = db.connection()
    total = conn.execute(f"SELECT COUNT(*) FROM request_log{clause}", args).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, ts, account_id, account, client, method, path, status,
               latency_ms, cached, error, provider_slug
          FROM request_log{clause}
         ORDER BY id DESC
         LIMIT ? OFFSET ?
        """,
        [*args, max(1, min(limit, 200)), max(0, offset)],
    ).fetchall()
    return {"total": total, "rows": [dict(r) for r in rows]}


def clear() -> int:
    conn = db.connection()
    with db.write_tx(conn) as c:
        cur = c.execute("DELETE FROM request_log")
        return cur.rowcount
