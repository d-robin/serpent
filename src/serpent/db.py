"""SQLite storage layer.

Design notes
------------
* WAL mode + ``BEGIN IMMEDIATE`` gives us correct cross-thread and
  cross-process (multi-worker) quota accounting on a single file.
* Connections are thread-local because ``sqlite3`` objects are not safe to
  share.  Each call site runs on the event loop's thread pool via
  ``asyncio.to_thread`` so a slow SD card never blocks request handling.
* Quota rows are keyed by ``(account_id, period)`` where ``period`` is
  ``YYYY-MM``.  A new month therefore needs no cron job: the first request in
  the new period simply inserts a fresh row with ``used = 0``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    label                TEXT    NOT NULL,
    api_key              TEXT    NOT NULL UNIQUE,
    quota_limit          INTEGER NOT NULL DEFAULT 250,
    status               TEXT    NOT NULL DEFAULT 'active',
    created_at           TEXT    NOT NULL,
    last_used_at         TEXT,
    last_error           TEXT,
    last_error_at        TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until       TEXT,
    notes                TEXT
);

CREATE TABLE IF NOT EXISTS usage (
    account_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    period           TEXT    NOT NULL,
    used             INTEGER NOT NULL DEFAULT 0,
    in_flight        INTEGER NOT NULL DEFAULT 0,
    ok               INTEGER NOT NULL DEFAULT 0,
    failed           INTEGER NOT NULL DEFAULT 0,
    refunded         INTEGER NOT NULL DEFAULT 0,
    latency_ms_sum   REAL    NOT NULL DEFAULT 0,
    latency_ms_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, period)
);

CREATE TABLE IF NOT EXISTS request_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    account_id INTEGER,
    account    TEXT,
    client     TEXT,
    method     TEXT,
    path       TEXT,
    status     INTEGER,
    latency_ms REAL,
    cached     INTEGER NOT NULL DEFAULT 0,
    error      TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    slug             TEXT    NOT NULL UNIQUE,
    name             TEXT    NOT NULL,
    preset           TEXT,
    base_url         TEXT    NOT NULL,
    auth_style       TEXT    NOT NULL DEFAULT 'header',
    auth_header_name TEXT    NOT NULL DEFAULT 'X-API-KEY',
    auth_param_name  TEXT    NOT NULL DEFAULT 'api_key',
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chains (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL,
    steps      TEXT    NOT NULL DEFAULT '[]',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log (ts);
CREATE INDEX IF NOT EXISTS idx_usage_period ON usage (period);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts (status);
"""

_local = threading.local()
_db_path: str | None = None
_init_lock = threading.Lock()


def configure(path: str | Path) -> None:
    """Point the module at a database file (also used by tests)."""
    global _db_path
    _db_path = str(Path(path).expanduser().resolve())


def db_path() -> str:
    if _db_path is None:
        raise RuntimeError("db.configure() must be called before use")
    return _db_path


def connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == db_path():
        return conn
    if conn is not None:  # path changed -> drop the stale handle
        try:
            conn.close()
        except sqlite3.Error:
            pass
    path = db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    _local.conn = conn
    _local.path = path
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection | None = None):
    """Serialise a write: BEGIN IMMEDIATE ... COMMIT / ROLLBACK."""
    conn = conn or connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        conn.execute("COMMIT")


@contextmanager
def read_tx(conn: sqlite3.Connection | None = None):
    conn = conn or connection()
    yield conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent upgrades for databases created by older versions."""
    if "provider_id" not in _columns(conn, "accounts"):
        conn.execute("ALTER TABLE accounts ADD COLUMN provider_id INTEGER REFERENCES providers(id)")
    if "provider_slug" not in _columns(conn, "request_log"):
        conn.execute("ALTER TABLE request_log ADD COLUMN provider_slug TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts (provider_id)")


def init_db(path: str | Path | None = None) -> None:
    with _init_lock:
        if path is not None:
            configure(path)
        _private_files()
        conn = connection()
        conn.executescript(SCHEMA)
        _migrate(conn)
        _private_files()  # the -wal/-shm files exist only once SQLite has opened the db


def _private_files() -> None:
    """The database holds provider API keys: keep it readable by its owner only (0600)."""
    base = Path(db_path())
    base.parent.mkdir(parents=True, exist_ok=True)
    if not base.exists():
        os.close(os.open(base, os.O_CREAT | os.O_WRONLY, 0o600))
    for suffix in ("", "-wal", "-shm"):
        try:
            os.chmod(f"{base}{suffix}", 0o600)
        except OSError:
            pass  # absent, or not ours to change


def close_current_thread() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None
            _local.path = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_state(key: str, default: str = "") -> str:
    row = connection().execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    with write_tx() as conn:
        conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_state_in(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state_in(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
