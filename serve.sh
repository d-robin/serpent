#!/usr/bin/env bash
# Run Serpent (router + Snake Charmer UI at /ui) in the foreground.
#
#   ./serve.sh                 # first free port from 8971 upward
#   ./serve.sh --dev           # router + Vite dev server with hot reload for ui/
#   SERPENT_PORT=9000 ./serve.sh
#   SERPENT_HOST=0.0.0.0 ./serve.sh      # listen on the LAN (default: loopback)
set -euo pipefail
cd "$(dirname "$0")"

DEV=0
[ "${1:-}" = "--dev" ] && DEV=1

HOST="${SERPENT_HOST:-127.0.0.1}"
PORT="${SERPENT_PORT:-${BIND_PORT:-8971}}"

in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    nc -z 127.0.0.1 "$1" >/dev/null 2>&1
  fi
}
free_port() {
  local p="$1"
  while in_use "$p"; do p=$((p + 1)); done
  echo "$p"
}

UVICORN=.venv/bin/uvicorn
[ -x "$UVICORN" ] || UVICORN="$(command -v uvicorn || true)"
[ -n "$UVICORN" ] || { echo "uvicorn not found - run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2; exit 1; }

REQUESTED="$PORT"
PORT="$(free_port "$PORT")"
[ "$PORT" != "$REQUESTED" ] && echo "port $REQUESTED is busy, using $PORT"

[ -f src/serpent/ui_dist/index.html ] || [ "$DEV" = 1 ] || \
  echo "note: Snake Charmer is not built (cd ui && npm ci && npm run build); /ui will show instructions."

export BIND_HOST="$HOST" BIND_PORT="$PORT"

if [ "$DEV" = 1 ]; then
  [ -d ui/node_modules ] || (cd ui && npm ci)
  VITE_PORT="$(free_port 5173)"
  echo "router   http://$HOST:$PORT"
  echo "UI (dev) http://127.0.0.1:$VITE_PORT/ui/"
  "$UVICORN" serpent.main:app --host "$HOST" --port "$PORT" --no-access-log &
  ROUTER=$!
  trap 'kill "$ROUTER" 2>/dev/null || true' EXIT INT TERM
  cd ui && SERPENT_API="http://$HOST:$PORT" npx vite --port "$VITE_PORT" --strictPort
else
  echo "Serpent         http://$HOST:$PORT"
  echo "Snake Charmer   http://$HOST:$PORT/ui/"
  exec "$UVICORN" serpent.main:app --host "$HOST" --port "$PORT" --no-access-log
fi
