#!/usr/bin/env bash
set -euo pipefail
desktop_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
desktop_python="$desktop_root/.venv-desktop/bin/python"
if [[ ! -x "$desktop_python" ]]; then
  echo 'Desktop environment missing. See README: install requirements-desktop.txt in .venv-desktop using CPython.' >&2
  exit 2
fi
export PYTHONUTF8=1
exec "$desktop_python" "$desktop_root/run_lan_codex_desktop.py" "$@"
