"""Manual live smoke test for the shared Codex App Server connection."""

from pathlib import Path

from lan_codex_share.codex_client import CodexClient
from lan_codex_share.state_store import StateStore


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    workspace = project_root.parents[1]
    state_path = project_root / "runtime" / "live-smoke-state.json"
    state = StateStore(state_path)
    client = CodexClient(workspace, state, turn_timeout_seconds=180)
    try:
        answer = client.run_turn("这是连接测试。不要执行命令或使用工具，只回复：局域网会话连接成功")
        print(answer)
        if "局域网会话连接成功" not in answer:
            raise RuntimeError("Live smoke response did not contain the expected marker")
        client.archive_thread()
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
