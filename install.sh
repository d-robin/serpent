#!/usr/bin/env bash
# One-shot setup from a source checkout: venv, editable install, `serpent init`.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 not found. On Raspberry Pi OS: sudo apt install -y python3 python3-venv" >&2
  exit 1
fi

VENV_CREATED=0
if [ ! -d .venv ]; then
  echo "==> creating virtualenv"
  "$PYTHON" -m venv .venv
  VENV_CREATED=1
fi

echo "==> installing serpent"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .

echo "==> initialising $(pwd -P)"
SERPENT_VENV_CREATED="$VENV_CREATED" SERPENT_HOME="$(pwd -P)" .venv/bin/serpent init

chmod +x ctl.sh install.sh 2>/dev/null || true
echo
echo "==> starting Serpent"
SERPENT_HOME="$(pwd -P)" .venv/bin/serpent up
echo "    later:     .venv/bin/serpent up | status | stop     (serpent --help for the rest)"
echo "    remove:    .venv/bin/serpent uninstall     (asks whether to keep your data)"
