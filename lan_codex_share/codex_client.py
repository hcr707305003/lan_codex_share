from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, Callable

from . import __version__
from .jsonrpc import JsonRpcClosed, JsonRpcConnection, JsonRpcError
from .state_store import StateStore
from .websocket_rpc import WebSocketJsonRpcConnection


class CodexClientError(RuntimeError):
    pass


class CodexTurnTimeout(CodexClientError):
    pass


class CodexClient:
    def __init__(
        self,
        workspace: str | Path,
        state: StateStore,
        turn_timeout_seconds: float = 1800,
        command: tuple[str, ...] | None = None,
        thread_name: str = "局域网共享 Codex 会话",
        remote_url: str | None = None,
        strict_resume: bool = False,
        sandbox_mode: str = "danger-full-access",
        logger: logging.Logger | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.state = state
        self.turn_timeout_seconds = turn_timeout_seconds
        self.command = command or self._default_command()
        self.thread_name = thread_name
        self.remote_url = remote_url
        self.strict_resume = strict_resume
        self.sandbox_mode = sandbox_mode
        self.logger = logger or logging.getLogger(__name__)
        self.process: subprocess.Popen[str] | None = None
        self.rpc: JsonRpcConnection | None = None
        self._lock = threading.RLock()
        self._turn_done = threading.Event()
        self._active_turn_id: str | None = None
        self._turn_error: str | None = None
        self._final_message: str | None = None
        self._delta_parts: list[str] = []
        self._delta_callback: Callable[[str], None] | None = None
        self._starting_turn = False
        self._thread_turn_id: str | None = None
        self._thread_idle = threading.Event()
        self._thread_idle.set()
        self._thread_state_handlers: list[Callable[[bool], None]] = []
        self._notification_handlers: list[Callable[[str, dict[str, Any]], None]] = []
        self._stderr_thread: threading.Thread | None = None
        self._model: str | None = None
        self._reasoning_effort: str | None = None
        self._service_tier: str | None = None

    @staticmethod
    def _default_command() -> tuple[str, ...]:
        candidates = ("codex.cmd", "codex.exe", "codex") if os.name == "nt" else ("codex",)
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                return (resolved, "app-server")
        return ("codex", "app-server")

    @property
    def active_turn_id(self) -> str | None:
        with self._lock:
            return self._active_turn_id

    @property
    def model_settings(self) -> dict[str, str | None]:
        with self._lock:
            return {
                "model": self._model,
                "reasoning_effort": self._reasoning_effort,
                "service_tier": self._service_tier,
            }

    def start(self) -> None:
        with self._lock:
            if self.rpc and (self.remote_url or (self.process and self.process.poll() is None)):
                return
            if self.remote_url:
                self.rpc = WebSocketJsonRpcConnection(self.remote_url, self.logger)
            else:
                self.process = subprocess.Popen(
                    list(self.command),
                    cwd=str(self.workspace),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if not self.process.stdin or not self.process.stdout:
                    raise CodexClientError("无法打开 Codex App Server stdio")
                self.rpc = JsonRpcConnection(self.process.stdout, self.process.stdin, self.logger)
            self.rpc.add_notification_handler(self._on_notification)
            self.rpc.set_server_request_handler(self._on_server_request)
            self.rpc.start()
            if self.process:
                self._stderr_thread = threading.Thread(
                    target=self._drain_stderr,
                    args=(self.process,),
                    name="codex-app-server-stderr",
                    daemon=True,
                )
                self._stderr_thread.start()
            result = self.rpc.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "lan_codex_share",
                        "title": "LAN Shared Codex Session",
                        "version": __version__,
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            if not isinstance(result, dict):
                raise CodexClientError("Codex App Server initialize 返回无效")
            self.rpc.notify("initialized", {})

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        if not process.stderr:
            return
        for _line in process.stderr:
            # Drain without logging content because it may contain user data.
            if process.poll() is not None:
                break

    def _thread_params(self) -> dict[str, Any]:
        return {
            "cwd": str(self.workspace),
            "approvalPolicy": "never",
            "sandbox": self.sandbox_mode,
        }

    def ensure_thread(self, force_new: bool = False) -> str:
        self.start()
        assert self.rpc is not None
        thread_id = None if force_new else self.state.thread_id
        if thread_id:
            try:
                result = self.rpc.request(
                    "thread/resume",
                    {"threadId": thread_id, **self._thread_params()},
                    timeout=60,
                )
                thread = (result or {}).get("thread", {})
                resumed = thread.get("id")
                if resumed:
                    self._capture_thread_settings(result)
                    self._apply_thread_status(thread)
                    return str(resumed)
            except JsonRpcError as exc:
                if self.strict_resume:
                    if "active writer" in exc.message.lower():
                        raise CodexClientError(
                            f"目标 Session {thread_id} 正被旧 Codex/VS Code 写入端占用。"
                            "请关闭旧客户端中的该会话，再重新运行共享启动器；"
                            "共享服务启动后，本机请改用 lan_codex_share cli 子命令；"
                            "源码环境也可使用 open_lan_codex_cli.cmd/.sh。"
                        ) from exc
                    raise CodexClientError(
                        f"无法恢复指定 Session {thread_id}：{exc.message}"
                    ) from exc
                self.logger.warning("Cannot resume saved Codex thread: %s", exc.code)

        result = self.rpc.request("thread/start", self._thread_params(), timeout=60)
        thread = (result or {}).get("thread", {})
        created = thread.get("id")
        if not created:
            raise CodexClientError("Codex 未返回 thread id")
        self._capture_thread_settings(result)
        self._apply_thread_status(thread)
        self.state.set_thread_id(str(created))
        try:
            self.rpc.request(
                "thread/name/set",
                {"threadId": str(created), "name": self.thread_name},
                timeout=15,
            )
        except JsonRpcError as exc:
            self.logger.warning("Cannot name Codex thread: %s", exc.code)
        return str(created)

    def _apply_thread_status(self, thread: dict[str, Any]) -> None:
        status = thread.get("status") or {}
        self._set_thread_busy(isinstance(status, dict) and status.get("type") == "active")

    def run_turn(self, text: str) -> str:
        return self.run_turn_items([{"type": "text", "text": text}])

    def run_turn_items(
        self,
        items: list[dict[str, Any]],
        on_delta: Callable[[str], None] | None = None,
        *,
        client_user_message_id: str | None = None,
        additional_context: dict[str, dict[str, str]] | None = None,
    ) -> str:
        if not items:
            raise CodexClientError("Codex turn 输入不能为空")
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return self._run_turn_once(items, on_delta, client_user_message_id, additional_context)
            except (JsonRpcClosed, BrokenPipeError, OSError) as exc:
                last_error = exc
                if attempt == 0:
                    self.logger.warning("App Server connection lost; restarting once")
                    with self._lock:
                        self._active_turn_id = None
                        self._turn_done.clear()
                    self._stop_process()
                    continue
                break
        raise CodexClientError(f"Codex App Server 连接失败：{type(last_error).__name__}")

    def _run_turn_once(
        self,
        items: list[dict[str, Any]],
        on_delta: Callable[[str], None] | None,
        client_user_message_id: str | None,
        additional_context: dict[str, dict[str, str]] | None,
    ) -> str:
        with self._lock:
            if self._active_turn_id:
                raise CodexClientError("已有 Codex turn 正在执行")
            self._turn_done.clear()
            self._turn_error = None
            self._final_message = None
            self._delta_parts = []
            self._delta_callback = on_delta
            self._starting_turn = True

        thread_id = self.ensure_thread()
        assert self.rpc is not None
        try:
            params: dict[str, Any] = {"threadId": thread_id, "input": items}
            if client_user_message_id:
                params["clientUserMessageId"] = client_user_message_id
            if additional_context:
                params["additionalContext"] = additional_context
            result = self.rpc.request("turn/start", params, timeout=60)
        except Exception:
            with self._lock:
                self._starting_turn = False
                self._delta_callback = None
            raise
        turn_id = (result or {}).get("turn", {}).get("id")
        if not turn_id:
            with self._lock:
                self._starting_turn = False
                self._delta_callback = None
            raise CodexClientError("Codex 未返回 turn id")
        with self._lock:
            self._active_turn_id = str(turn_id)
            self._starting_turn = False

        if not self._turn_done.wait(self.turn_timeout_seconds):
            self.interrupt_turn()
            with self._lock:
                self._active_turn_id = None
                self._starting_turn = False
                self._delta_callback = None
            raise CodexTurnTimeout("Codex 任务超过配置的执行时间")

        with self._lock:
            error = self._turn_error
            final = self._final_message or "".join(self._delta_parts).strip()
            self._active_turn_id = None
            self._delta_callback = None
        if error:
            raise CodexClientError(error)
        if not final:
            raise CodexClientError("Codex 已完成，但没有返回最终文本")
        return final

    @property
    def thread_busy(self) -> bool:
        return not self._thread_idle.is_set()

    def wait_for_thread_idle(self, timeout: float | None = None) -> bool:
        return self._thread_idle.wait(timeout)

    def add_thread_state_handler(self, handler: Callable[[bool], None]) -> None:
        self._thread_state_handlers.append(handler)

    def add_notification_handler(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        self._notification_handlers.append(handler)

    def read_thread(self, include_turns: bool = True) -> dict[str, Any]:
        thread_id = self.ensure_thread()
        assert self.rpc is not None
        result = self.rpc.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": include_turns},
            timeout=60,
        )
        thread = (result or {}).get("thread")
        if not isinstance(thread, dict) or not thread.get("id"):
            raise CodexClientError("Codex thread/read 返回无效")
        self._apply_thread_status(thread)
        return thread

    def list_models(self) -> list[dict[str, Any]]:
        self.start()
        assert self.rpc is not None
        models: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            result = self.rpc.request("model/list", params, timeout=60)
            for raw in (result or {}).get("data", []):
                if not isinstance(raw, dict):
                    continue
                model = str(raw.get("model") or "").strip()
                if not model:
                    continue
                efforts = []
                for option in raw.get("supportedReasoningEfforts", []):
                    if not isinstance(option, dict):
                        continue
                    value = str(option.get("reasoningEffort") or "").strip()
                    if value:
                        efforts.append({"value": value, "description": str(option.get("description") or "")})
                tiers = []
                for tier in raw.get("serviceTiers", []):
                    if not isinstance(tier, dict):
                        continue
                    tier_id = str(tier.get("id") or "").strip()
                    if tier_id:
                        tiers.append({
                            "id": tier_id,
                            "name": str(tier.get("name") or tier_id),
                            "description": str(tier.get("description") or ""),
                        })
                models.append({
                    "id": str(raw.get("id") or model),
                    "model": model,
                    "display_name": str(raw.get("displayName") or model),
                    "description": str(raw.get("description") or ""),
                    "is_default": bool(raw.get("isDefault")),
                    "default_reasoning_effort": str(raw.get("defaultReasoningEffort") or ""),
                    "supported_reasoning_efforts": efforts,
                    "default_service_tier": raw.get("defaultServiceTier"),
                    "service_tiers": tiers,
                })
            cursor = (result or {}).get("nextCursor")
            if not cursor:
                return models

    def list_threads(self) -> list[dict[str, Any]]:
        self.start()
        assert self.rpc is not None
        threads_by_id: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "archived": False,
                "limit": 100,
                "sortDirection": "desc",
                "sortKey": "recency_at",
            }
            if cursor:
                params["cursor"] = cursor
            result = self.rpc.request("thread/list", params, timeout=60)
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise CodexClientError("Codex thread/list 返回无效")
            for raw in result["data"]:
                if not isinstance(raw, dict):
                    raise CodexClientError("Codex thread/list 返回无效 Session")
                thread_id = str(raw.get("id") or "").strip()
                if not thread_id:
                    raise CodexClientError("Codex thread/list 返回缺少 Session ID")
                if raw.get("ephemeral") is True or raw.get("parentThreadId"):
                    continue
                threads_by_id.setdefault(thread_id, dict(raw))
            next_cursor = result.get("nextCursor")
            if next_cursor is None or next_cursor == "":
                break
            if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
                raise CodexClientError("Codex thread/list 返回无效分页游标")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        def recency(thread: dict[str, Any]) -> int:
            for key in ("recencyAt", "updatedAt", "createdAt"):
                value = thread.get(key)
                if isinstance(value, (int, float)):
                    return int(value)
            return 0

        return sorted(threads_by_id.values(), key=recency, reverse=True)

    def update_thread_settings(
        self, model: str, reasoning_effort: str, service_tier: str | None
    ) -> dict[str, str | None]:
        selected_model = model.strip()
        selected_effort = reasoning_effort.strip()
        if not selected_model or not selected_effort:
            raise ValueError("模型和思考强度不能为空")
        thread_id = self.ensure_thread()
        assert self.rpc is not None
        self.rpc.request(
            "thread/settings/update",
            {
                "threadId": thread_id,
                "model": selected_model,
                "effort": selected_effort,
                "serviceTier": service_tier,
            },
            timeout=30,
        )
        self._capture_thread_settings({
            "model": selected_model,
            "reasoningEffort": selected_effort,
            "serviceTier": service_tier,
        })
        return self.model_settings

    def _capture_thread_settings(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        with self._lock:
            model = payload.get("model")
            if isinstance(model, str) and model.strip():
                self._model = model.strip()
            if "effort" in payload:
                effort = payload.get("effort")
                self._reasoning_effort = effort.strip() if isinstance(effort, str) and effort.strip() else None
            elif "reasoningEffort" in payload:
                effort = payload.get("reasoningEffort")
                self._reasoning_effort = effort.strip() if isinstance(effort, str) and effort.strip() else None
            if "serviceTier" in payload:
                tier = payload.get("serviceTier")
                self._service_tier = tier.strip() if isinstance(tier, str) and tier.strip() else None

    def _set_thread_busy(self, busy: bool) -> None:
        changed = busy == self._thread_idle.is_set()
        if busy:
            self._thread_idle.clear()
        else:
            self._thread_idle.set()
        if changed:
            for handler in list(self._thread_state_handlers):
                try:
                    handler(busy)
                except Exception:
                    self.logger.exception("Thread state handler failed")

    def interrupt_turn(self) -> bool:
        with self._lock:
            turn_id = self._active_turn_id
            thread_id = self.state.thread_id
        if not turn_id or not thread_id or not self.rpc:
            return False
        self.rpc.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=15,
        )
        return True

    def archive_thread(self) -> bool:
        thread_id = self.state.thread_id
        if not thread_id:
            return False
        self.start()
        assert self.rpc is not None
        self.rpc.request("thread/archive", {"threadId": thread_id}, timeout=30)
        self.state.set_thread_id(None)
        return True

    def new_thread(self) -> str:
        if self.active_turn_id:
            raise CodexClientError("当前任务仍在执行")
        self.archive_thread()
        return self.ensure_thread(force_new=True)

    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "thread/settings/updated":
            self._capture_thread_settings(params.get("threadSettings"))
        for handler in list(self._notification_handlers):
            try:
                handler(method, params)
            except Exception:
                self.logger.exception("Codex notification handler failed for %s", method)
        if method == "turn/started":
            turn = params.get("turn") or {}
            turn_id = turn.get("id")
            if turn_id:
                with self._lock:
                    self._thread_turn_id = str(turn_id)
                    if self._starting_turn and not self._active_turn_id:
                        self._active_turn_id = str(turn_id)
                self._set_thread_busy(True)
            return
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str):
                with self._lock:
                    incoming_turn = params.get("turnId")
                    if not (self._starting_turn or self._active_turn_id):
                        return
                    if incoming_turn and self._active_turn_id and str(incoming_turn) != self._active_turn_id:
                        return
                    self._delta_parts.append(delta)
                    callback = self._delta_callback
                if callback:
                    try:
                        callback(delta)
                    except Exception:
                        self.logger.exception("Agent message delta callback failed")
            return
        if method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    with self._lock:
                        if not (self._starting_turn or self._active_turn_id):
                            return
                        self._final_message = text.strip()
            return
        if method == "turn/completed":
            turn = params.get("turn") or {}
            completed_id = str(turn.get("id") or "")
            status = turn.get("status")
            error = turn.get("error")
            with self._lock:
                if not self._active_turn_id and self._starting_turn and completed_id:
                    self._active_turn_id = completed_id
                is_own_turn = bool(self._active_turn_id and (not completed_id or completed_id == self._active_turn_id))
                if completed_id and (not self._thread_turn_id or completed_id == self._thread_turn_id):
                    self._thread_turn_id = None
                    self._set_thread_busy(False)
                if not is_own_turn:
                    return
                if status not in {None, "completed"}:
                    if isinstance(error, dict):
                        self._turn_error = str(error.get("message") or status)
                    else:
                        self._turn_error = str(error or status)
            self._turn_done.set()

    def _on_server_request(self, message: dict[str, Any]) -> None:
        if self.rpc:
            self.rpc.respond_error(int(message["id"]), -32601, "Interactive requests are disabled")

    def _stop_process(self) -> None:
        rpc, process = self.rpc, self.process
        self.rpc = None
        self.process = None
        if rpc:
            rpc.close()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1)
        self._stderr_thread = None

    def close(self) -> None:
        self._stop_process()
