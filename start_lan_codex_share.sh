#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]; then
  PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
else
  echo "[ERROR] Missing project virtual environment." >&2
  echo "macOS/Linux: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  echo "Windows Git Bash: python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt" >&2
  exit 1
fi

CONFIG="$SCRIPT_DIR/lan_config.toml"
if [ ! -f "$CONFIG" ]; then
  echo "[ERROR] Missing lan_config.toml. Copy lan_config.example.toml and check workspace." >&2
  exit 2
fi

exec "$PYTHON" -m lan_codex_share --config "$CONFIG" "$@"
