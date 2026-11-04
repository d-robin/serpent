#!/usr/bin/env bash
# Throwaway demo: a fake provider plus five seeded accounts, so you can click
# around the dashboard and fire test searches without spending real credits.
#
#   ./scripts/demo.sh             # dashboard on http://127.0.0.1:8980
#   DEMO_PORT=9100 ./scripts/demo.sh
#
# Nothing here touches the live database or .env: it uses data/demo.db, starts
# the fake provider on 9911, and runs with auth disabled.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
DB=data/demo.db
PORT="${DEMO_PORT:-8980}"
UPSTREAM_PORT="${FAKE_UPSTREAM_PORT:-9911}"

[ -x "$PY" ] || { echo "run ./install.sh first" >&2; exit 1; }
mkdir -p data
rm -f "$DB" "$DB-wal" "$DB-shm"

echo "==> seeding demo accounts"
DB_PATH="$DB" "$PY" - <<'PY'
from datetime import datetime, timedelta, timezone

from serpent import accounts, db, quota
from serpent.config import load_settings

s = load_settings()
db.init_db(s.db_path)
period = quota.current_period(reset_day=s.quota_reset_day)
conn = db.connection()

rows = [
    # label          key            limit  status     used
    ("serper-a",     "demo-key-a",  250,   "active",   12),
    ("serper-b",     "demo-key-b",  250,   "active",   63),
    ("serper-c",     "demo-key-c",  250,   "active",  201),
    ("scrapingdog",  "demo-key-d",  100,   "disabled",  4),
    ("valueserp",    "demo-key-e",  250,   "invalid",   0),
]

ids = {}
for label, key, limit, status, used in rows:
    acc = accounts.add_account(key, label=label, quota_limit=limit)
    ids[label] = acc["id"]
    if used:
        with db.write_tx(conn):
            conn.execute(
                """
                INSERT INTO usage (account_id, period, used, ok, failed,
                                   latency_ms_sum, latency_ms_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, period) DO UPDATE SET used = excluded.used
                """,
                (acc["id"], period, used, used, used // 20, used * 240.0, used),
            )

accounts.update_account(ids["scrapingdog"], status="disabled")
accounts.mark_invalid(ids["valueserp"], "401 from provider")

now = datetime.now(timezone.utc)
log = [
    ("serper-a", "/search", 200, 412.5, 1),
    ("serper-b", "/search", 200, 388.1, 3),
    ("serper-c", "/search", 200, 903.4, 4),
    ("serper-b", "/search", 200, 355.9, 5),
    ("serper-c", "/search", 502, 5021.0, 6),
    ("serper-a", "/news", 200, 470.2, 9),
    ("serper-b", "/search", 200, 401.7, 11),
]
with db.write_tx(conn):
    for label, path, status, ms, minutes in log:
        conn.execute(
            """
            INSERT INTO request_log
                (ts, account_id, account, client, method, path, status,
                 latency_ms, cached, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S"),
                ids[label], label, "demo", "POST", path, status,
                ms, 0, "upstream 502" if status >= 400 else None,
            ),
        )

print(f"    {len(rows)} accounts, period {period}")
PY

echo "==> starting fake provider on 127.0.0.1:$UPSTREAM_PORT"
FAKE_UPSTREAM_PORT="$UPSTREAM_PORT" "$PY" scripts/fake_upstream.py >data/demo-upstream.log 2>&1 &
UP=$!
trap 'kill "$UP" 2>/dev/null || true' EXIT INT TERM
sleep 0.6
kill -0 "$UP" 2>/dev/null || { echo "fake provider failed to start:" >&2; tail -5 data/demo-upstream.log >&2; exit 1; }

echo
echo "Try:  curl -s -X POST http://127.0.0.1:$PORT/v1/search \\"
echo "        -H 'Content-Type: application/json' -d '{\"q\":\"coffee austin\"}' | head -c 300"
echo

DB_PATH="$DB" \
UPSTREAM_BASE_URL="http://127.0.0.1:$UPSTREAM_PORT" \
ROUTER_KEYS= \
SERPENT_PORT="$PORT" \
"$(pwd)/serve.sh"
