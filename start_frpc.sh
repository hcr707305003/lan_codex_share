#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [frpc-config.toml]" >&2
  exit 2
fi
FRPC_CONFIG=${1:-"$SCRIPT_DIR/frpc.toml"}
if [ ! -f "$FRPC_CONFIG" ]; then
  echo "[ERROR] Missing frpc config. Copy frpc.example.toml to frpc.toml and edit it." >&2
  exit 2
fi
if [ -x "$SCRIPT_DIR/frpc" ]; then
  FRPC_EXEC="$SCRIPT_DIR/frpc"
elif [ -x "$SCRIPT_DIR/frpc.exe" ]; then
  FRPC_EXEC="$SCRIPT_DIR/frpc.exe"
elif command -v frpc >/dev/null 2>&1; then
  FRPC_EXEC=$(command -v frpc)
else
  echo "[ERROR] Install frpc beside this script or on PATH. Share must be started separately." >&2
  exit 1
fi
exec "$FRPC_EXEC" -c "$FRPC_CONFIG"
