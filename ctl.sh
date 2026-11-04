#!/usr/bin/env bash
# Thin shim kept for muscle memory: everything lives in the `serpent` command.
here="$(cd "$(dirname "$0")" && pwd)"
export SERPENT_HOME="${SERPENT_HOME:-$here}"
if [ -x "$here/.venv/bin/serpent" ]; then
  exec "$here/.venv/bin/serpent" "$@"
fi
exec "${PYTHON:-python3}" -m serpent "$@"
