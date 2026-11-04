#!/usr/bin/env bash
# End-to-end smoke test: real HTTP, real SQLite, fake provider, real failover.
# Usage: ./scripts/smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
[ -x "$PY" ] || { echo "run ./install.sh first" >&2; exit 1; }

WORK="$(mktemp -d)"
DB="$WORK/smoke.db"
ROUTER_PORT=18099
ADMIN="smoke-admin"
CLIENT="smoke-client"
BASE="http://127.0.0.1:${ROUTER_PORT}"
UPSTREAM="http://127.0.0.1:9911"
pids=()

cleanup() {
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "  ok  $*"; }
hdr() { tr -d '\r' | awk -F': ' -v k="$(printf '%s' "$1" | tr 'A-Z' 'a-z')" 'tolower($1)==k{print $2}'; }

echo "==> starting fake SERP provider on $UPSTREAM"
$PY scripts/fake_upstream.py & pids+=($!)

echo "==> starting router on $BASE"
DB_PATH="$DB" UPSTREAM_BASE_URL="$UPSTREAM" ROUTER_KEYS="$ADMIN:admin,$CLIENT:client" \
  BIND_PORT=$ROUTER_PORT CACHE_TTL_SECONDS=30 \
  .venv/bin/uvicorn serpent.main:app --host 127.0.0.1 --port $ROUTER_PORT \
  --no-access-log --log-level warning & pids+=($!)

for _ in $(seq 1 60); do
  curl -fsS "$BASE/healthz" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -fsS "$BASE/healthz" >/dev/null || fail "router did not come up"
pass "healthz"

add() {
  curl -fsS -X POST "$BASE/admin/accounts" -H "X-Router-Key: $ADMIN" \
    -H 'Content-Type: application/json' \
    -d "{\"label\":\"$1\",\"api_key\":\"$2\",\"quota_limit\":$3}" -o /dev/null ||
    fail "could not add account $1"
}

echo "==> registering three accounts (the first has a revoked key)"
add acct-revoked bad-key 3
add acct-good-1 good-key-1 3
add acct-good-2 good-key-2 3
pass "3 accounts added"

TOTAL=$(curl -fsS "$BASE/v1/quota" -H "X-Router-Key: $CLIENT" |
  $PY -c 'import json,sys;print(json.load(sys.stdin)["quota_limit_total"])')
[ "$TOTAL" = "9" ] || fail "expected 9 total credits, got $TOTAL"
pass "quota endpoint reports 9 credits across 3 accounts"

echo "==> a revoked key must fail over, not fail the request"
OUT=$(curl -fsS -D - -o /dev/null -X POST "$BASE/v1/search" -H "X-Router-Key: $CLIENT" \
  -H 'Content-Type: application/json' -d '{"q":"failover"}')
CODE=$(printf '%s' "$OUT" | head -1 | awk '{print $2}')
ACCOUNT=$(printf '%s' "$OUT" | hdr X-Router-Account)
ATTEMPTS=$(printf '%s' "$OUT" | hdr X-Router-Attempts)
[ "$CODE" = "200" ] || fail "failover request returned $CODE"
[ "$ATTEMPTS" = "2" ] || fail "expected 2 attempts, got $ATTEMPTS"
[ "$ACCOUNT" = "acct-good-1" ] || fail "expected acct-good-1 to serve, got $ACCOUNT"
REVOKED=$(curl -fsS "$BASE/admin/accounts" -H "X-Router-Key: $ADMIN" |
  $PY -c 'import json,sys;print([a["status"] for a in json.load(sys.stdin)["accounts"] if a["label"]=="acct-revoked"][0])')
[ "$REVOKED" = "invalid" ] || fail "revoked key should be marked invalid, got $REVOKED"
REVOKED_USED=$(curl -fsS "$BASE/admin/accounts" -H "X-Router-Key: $ADMIN" |
  $PY -c 'import json,sys;print([a["used"] for a in json.load(sys.stdin)["accounts"] if a["label"]=="acct-revoked"][0])')
[ "$REVOKED_USED" = "0" ] || fail "failed attempt should be refunded, used=$REVOKED_USED"
pass "401 -> refunded, account marked invalid, retried on a healthy account"

echo "==> rotation spreads load and decrements quota"
for i in 1 2 3 4; do
  H=$(curl -fsS -D - -o /dev/null -X POST "$BASE/v1/search" -H "X-Router-Key: $CLIENT" \
    -H 'Content-Type: application/json' -d "{\"q\":\"query $i\"}")
  echo "     request $i -> account=$(printf '%s' "$H" | hdr X-Router-Account) remaining=$(printf '%s' "$H" | hdr X-Quota-Remaining)"
  [ -n "$(printf '%s' "$H" | hdr X-Router-Account)" ] || fail "no account header on request $i"
done
pass "every request reported which account served it"

echo "==> upstream response is proxied verbatim"
PROVIDER=$(curl -fsS -X POST "$BASE/v1/search" -H "X-Router-Key: $CLIENT" \
  -H 'Content-Type: application/json' -d '{"q":"echo"}' |
  $PY -c 'import json,sys;d=json.load(sys.stdin);print(d["provider"], d["key_seen"][:4])')
[ "${PROVIDER%% *}" = "fake-serp" ] || fail "body was not proxied through"
pass "provider JSON returned untouched ($PROVIDER)"

echo "==> cache hit costs no quota"
BEFORE=$(curl -fsS "$BASE/v1/quota" -H "X-Router-Key: $CLIENT" |
  $PY -c 'import json,sys;print(json.load(sys.stdin)["quota_used_total"])')
H=$(curl -fsS -D - -o /dev/null -X POST "$BASE/v1/search" -H "X-Router-Key: $CLIENT" \
  -H 'Content-Type: application/json' -d '{"q":"echo"}')
AFTER=$(curl -fsS "$BASE/v1/quota" -H "X-Router-Key: $CLIENT" |
  $PY -c 'import json,sys;print(json.load(sys.stdin)["quota_used_total"])')
[ "$(printf '%s' "$H" | hdr X-Cache)" = "HIT" ] || fail "expected a cache hit"
[ "$BEFORE" = "$AFTER" ] || fail "cache hit consumed quota ($BEFORE -> $AFTER)"
pass "duplicate served from cache with $BEFORE credits still used"

echo "==> running the pool dry yields 429"
for _ in $(seq 1 12); do
  CODE=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/search" \
    -H "X-Router-Key: $CLIENT" -H 'Content-Type: application/json' -d "{\"q\":\"fill $_\"}")
  [ "$CODE" = "429" ] && break
done
[ "$CODE" = "429" ] || fail "expected 429 once exhausted, got $CODE"
RA=$(curl -sS -D - -o /dev/null -X POST "$BASE/v1/search" -H "X-Router-Key: $CLIENT" \
  -H 'Content-Type: application/json' -d '{"q":"after"}' | hdr Retry-After)
[ -n "$RA" ] || fail "429 missing Retry-After"
pass "exhaustion returns 429 with Retry-After: ${RA}s"

echo "==> bookkeeping adds up"
curl -fsS "$BASE/api/status" | $PY -c '
import json,sys
s = json.load(sys.stdin)
assert s["accounts_total"] == 3, s["accounts_total"]
assert s["accounts_invalid"] == 1, s["accounts_invalid"]
assert s["accounts_usable"] == 0, s["accounts_usable"]
assert s["quota_available_total"] == 0, s["quota_available_total"]
assert s["quota_used_total"] == 6, s["quota_used_total"]  # two healthy accounts x 3
assert s["requests_refunded"] >= 1
assert sum(a["used"] for a in s["accounts"]) == s["quota_used_total"]
print("  ok  %d/%d credits used, %d refunded, %d invalid, can_serve=%s"
      % (s["quota_used_total"], s["quota_limit_total"], s["requests_refunded"],
         s["accounts_invalid"], s["can_serve"]))
'

echo "==> dashboard, metrics, readiness"
curl -fsS "$BASE/" | grep -q "SERP" || fail "dashboard did not render"
pass "dashboard renders"
curl -fsS "$BASE/metrics" -H "X-Router-Key: $CLIENT" |
  grep -q "serpent_quota_remaining" || fail "metrics missing"
pass "prometheus metrics exposed"
[ "$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/readyz")" = "503" ] ||
  fail "readyz should be 503 with no credits left"
pass "readyz drops to 503 when the pool is dry"
[ "$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/healthz")" = "200" ] ||
  fail "healthz should stay 200"
pass "healthz stays 200 (liveness != readiness)"

echo "==> auth enforcement"
[ "$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/v1/quota")" = "401" ] ||
  fail "unauthenticated read should be 401"
pass "unauthenticated read rejected"
[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/admin/reset" \
  -H "X-Router-Key: $CLIENT")" = "403" ] || fail "client key should not reset"
pass "client key cannot perform admin actions"
[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/search?q=x" \
  -H "X-Router-Key: $CLIENT")" != "401" ] || fail "client key should be able to proxy"
pass "client key can proxy"

echo "==> cli"
DB_PATH="$DB" .venv/bin/serpent accounts list | tail -5

echo
echo "ALL SMOKE CHECKS PASSED"
