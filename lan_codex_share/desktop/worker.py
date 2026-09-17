from __future__ import annotations

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import threading


def listen_control(stream, stop_event: threading.Event) -> None:
    for line in stream:
        try:
            if json.loads(line) == {"command": "stop"}:
                stop_event.set()
                return
        except (ValueError, TypeError):
            continue
    stop_event.set()


def run_worker(config_path: Path) -> int:
    from ..lan_main import run
    stop_event = threading.Event()
    output = sys.stdout
    threading.Thread(target=listen_control, args=(sys.stdin, stop_event), daemon=True).start()

    def ready():
        output.write('{"desktop_event":"ready"}\n')
        output.flush()

    def owned(processes):
        identities = []
        for process in processes:
            try:
                identities.append([process.pid, process.create_time()])
            except Exception:
                continue
        output.write(json.dumps({'desktop_event': 'owned', 'processes': identities}) + '\n')
        output.flush()

    with redirect_stdout(sys.stderr):
        return run(config_path, stop_event=stop_event, on_ready=ready, on_owned=owned)


if __name__ == "__main__":
    raise SystemExit(run_worker(Path(sys.argv[1])))
