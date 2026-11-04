"""Recent-request ring buffer, persisted so the dashboard survives restarts."""

from __future__ import annotations

from . import db


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


def clear() -> int:
    conn = db.connection()
    with db.write_tx(conn) as c:
        cur = c.execute("DELETE FROM request_log")
        return cur.rowcount
