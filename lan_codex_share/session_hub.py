from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import queue
import threading
from typing import Any, Iterable
from .project_profiles import project_key


class LanSessionHub:
    """Route browser operations to isolated chat services and fan out live updates."""

    def __init__(
        self,
        services: Iterable[Any] = (),
        logger=None,
        *,
        catalog_client=None,
        service_factory=None,
        refresh_seconds: float = 5.0,
    ):
        self._services = list(services)
        self._catalog_client = catalog_client
        self._service_factory = service_factory
        self._catalog_mode = catalog_client is not None or service_factory is not None
        if self._catalog_mode and (catalog_client is None or service_factory is None):
            raise ValueError("目录模式需要 catalog_client 和 service_factory")
        if self._catalog_mode and self._services:
            raise ValueError("目录模式不能同时传入静态 Session 服务")
        self.logger = logger
        self._services_by_id: dict[str, Any] = {}
        self._added_by_id: dict[str, dict[str, Any]] = {}
        self.tasks = None
        self.profiles = None
        self._added_factory = None
        self._catalog_by_id: dict[str, dict[str, Any]] = {}
        self._thread_names: dict[str, dict[str, Any]] = {}
        self._session_errors: dict[str, str] = {}
        self._catalog_error: str | None = None
        self._default_session_id: str | None = None
        self._subscribers: set[queue.Queue[int]] = set()
        self._lock = threading.RLock()
        self._service_create_lock = threading.RLock()
        self._fixed_ids = None
        self._version = 0
        self._refresh_seconds = max(0.1, float(refresh_seconds))
        self._stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None
        for service in self._services:
            service.add_change_handler(self._service_changed)

    @property
    def thread_ids(self) -> tuple[str, ...]:
        with self._lock:
            base = self._catalog_by_id if self._catalog_mode else self._services_by_id
            return tuple(sid for sid in dict.fromkeys((*base, *self._added_by_id))
                         if self._fixed_ids is None or sid in self._fixed_ids)

    def fix_membership(self, ids):
        with self._lock:
            self._fixed_ids = set(ids)
            if self._default_session_id not in self.thread_ids:
                self._default_session_id = next(iter(self.thread_ids), None)

    def remove_shared(self, sid, source_ip, persist, remaining):
        with self._service_create_lock:
            with self._lock:
                service = self._services_by_id.get(sid)
                metadata = self._catalog_by_id.get(sid) or self._added_by_id.get(sid) or {}
            if service is not None:
                service.release_session(source_ip)
            elif metadata.get('status') == 'active' or (isinstance(metadata.get('status'), dict) and metadata['status'].get('type') == 'active'):
                raise ValueError('任务执行中，暂时不能移出共享')
            persist()  # On failure keep the released service visible for retry.
            with self._lock:
                self._services_by_id.pop(sid, None)
                self._added_by_id.pop(sid, None)
                self._catalog_by_id.pop(sid, None)
                self._thread_names.pop(sid, None)
                self._session_errors.pop(sid, None)
                self.fix_membership(remaining)
            if service is not None:
                service.close()
                if service in self._services:
                    self._services.remove(service)
            self._broadcast()

    def configure_tasks(self, tasks, factory) -> None:
        self.tasks = tasks
        self._added_factory = factory

    def register_session(self, metadata) -> None:
        with self._lock:
            self._added_by_id[metadata['id']] = deepcopy(metadata)
            if metadata.get('error'):
                self._session_errors[metadata['id']] = metadata['error']
            else:
                self._session_errors.pop(metadata['id'], None)
            if self._default_session_id is None:
                self._default_session_id = metadata['id']
        self._broadcast()

    def _restore_tasks(self):
        if self.tasks:
            try:
                self.tasks.restore()
            except ValueError as exc:
                self._catalog_error = str(exc)
                if self.logger:
                    self.logger.warning('%s', exc)

    @property
    def catalog_mode(self) -> bool:
        return self._catalog_mode

    @property
    def preview_roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        with self._lock:
            entries = list(self._catalog_by_id.values())
        for entry in entries:
            raw = entry.get("cwd")
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                path = Path(raw).expanduser().resolve()
            except (OSError, ValueError):
                continue
            if path.is_dir() and path not in roots:
                roots.append(path)
        return tuple(roots)

    def start(self) -> None:
        if self._catalog_mode:
            self._catalog_client.start()
            try:
                self.refresh_catalog()
            except Exception as exc:
                self._set_catalog_error(exc)
            self._stop.clear()
            self._refresh_thread = threading.Thread(
                target=self._refresh_loop,
                name="lan-session-catalog",
                daemon=True,
            )
            self._refresh_thread.start()
            self._restore_tasks()
            return
        mapped: dict[str, Any] = {}
        for service in self._services:
            service.start()
            thread_id = str(service.thread_id or "").strip()
            if not thread_id:
                raise ValueError("Session 服务启动后未返回 Session ID")
            if thread_id in mapped:
                raise ValueError(f"Session ID 重复：{thread_id}")
            mapped[thread_id] = service
        with self._lock:
            self._services_by_id = mapped
            self._default_session_id = next(iter(mapped), None)
        self._restore_tasks()
        self._broadcast()
        if self.tasks and hasattr(self.tasks.client, 'list_threads'):
            self._stop.clear()
            self._refresh_thread = threading.Thread(target=self._refresh_loop,
                name='lan-session-metadata', daemon=True)
            self._refresh_thread.start()

    def resolve_session_id(self, session_id: Any = None) -> str:
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("session_id 必须是字符串")
        requested = session_id.strip() if isinstance(session_id, str) else ""
        with self._lock:
            selected = requested or self._default_session_id
            if self._fixed_ids is not None and selected not in self._fixed_ids:
                raise ValueError('指定的 Session 不在共享列表中')
            allowed = self._catalog_by_id if self._catalog_mode else self._services_by_id
            if not selected or (selected not in allowed and selected not in self._services_by_id and selected not in self._added_by_id):
                raise ValueError("指定的 Session 不在共享列表中")
            return selected

    def _service(self, session_id: Any = None):
        with self._service_create_lock:
            return self._service_locked(session_id)

    def _service_locked(self, session_id: Any = None):
        selected = self.resolve_session_id(session_id)
        with self._lock:
            service = self._services_by_id.get(selected)
        if service is not None:
            return selected, service
        with self._service_create_lock:
            with self._lock:
                service = self._services_by_id.get(selected)
                metadata = deepcopy(self._added_by_id.get(selected) or self._catalog_by_id.get(selected))
                factory = self._added_factory if selected in self._added_by_id else self._service_factory
            if service is not None:
                return selected, service
            if metadata is None or factory is None:
                raise ValueError("指定的 Session 不在共享列表中")
            service = None
            try:
                if metadata.get('error'):
                    raise ValueError(metadata['error'])
                service = factory(metadata)
                service.add_change_handler(self._service_changed)
                service.start()
                actual_id = str(service.thread_id or "").strip()
                if actual_id != selected:
                    raise ValueError("恢复后的 Session ID 与目录不一致")
            except Exception as exc:
                if service is not None:
                    try:
                        service.close()
                    except Exception:
                        pass
                message = f"无法加载 Session {selected}：{exc}"
                with self._lock:
                    self._session_errors[selected] = message
                self._broadcast()
                raise ValueError(message) from exc
            with self._lock:
                self._services_by_id[selected] = service
                self._session_errors.pop(selected, None)
            self._broadcast()
            return selected, service

    def snapshot(self, session_id: Any = None, history_limit: int | None = None, before: str | None = None) -> dict[str, Any]:
        # Membership fallback and lookup must be atomic with remove_shared().
        # Otherwise an SSE reader can validate an ID, wait for removal, then
        # attempt to load the now-removed session and break its live stream.
        with self._service_create_lock:
            return self._snapshot_locked(session_id, history_limit, before)

    def _snapshot_locked(self, session_id, history_limit, before):
        if self._fixed_ids is not None and isinstance(session_id, str) and session_id not in self.thread_ids:
            session_id = None
        if session_id is None:
            with self._lock:
                if self._default_session_id is None:
                    return self._empty_snapshot()
        selected, service = self._service(session_id)
        snapshot = service.snapshot() if history_limit is None else service.snapshot(history_limit=history_limit, before=before)
        snapshot['thread'] = dict(snapshot.get('thread') or {})
        self._apply_name(selected, snapshot['thread'])
        snapshot["selected_session_id"] = selected
        snapshot["sessions"] = self.session_summaries()
        snapshot["projects"] = self.project_summaries()
        snapshot["catalog_mode"] = self._catalog_mode
        snapshot["catalog_error"] = self._catalog_error
        with self._lock:
            snapshot["hub_version"] = self._version
        return snapshot

    def activities(self, session_id: Any, turn_id: str, epoch: str, before: str | None = None) -> dict[str, Any]:
        _selected, service = self._service(session_id)
        return service.activities(turn_id, epoch, before)

    def _empty_snapshot(self) -> dict[str, Any]:
        with self._lock:
            version = self._version
            error = self._catalog_error
        return {
            "thread_id": None,
            "selected_session_id": None,
            "sessions": [],
            "projects": [],
            "catalog_mode": True,
            "catalog_error": error,
            "status": "idle",
            "connection": "disconnected",
            "queue_size": 0,
            "version": version,
            "hub_version": version,
            "thread": {"turns": []},
            "pending": [],
            "model_catalog": [],
            "model_settings": {},
            "last_error": error or "没有可共享的 Codex Session。",
            "last_notice": None,
        }

    def session_summaries(self) -> list[dict[str, Any]]:
        if self._catalog_mode or self._added_by_id:
            with self._lock:
                merged = dict(self._catalog_by_id)
                if not self._catalog_mode:
                    merged.update({sid: {} for sid in self._services_by_id})
                merged.update(self._added_by_id)
                entries = list(merged.items())
                services = dict(self._services_by_id)
                errors = dict(self._session_errors)
            summaries: list[dict[str, Any]] = []
            for thread_id, entry in entries:
                if self._fixed_ids is not None and thread_id not in self._fixed_ids:
                    continue
                service = services.get(thread_id)
                if service is not None:
                    value = deepcopy(service.summary())
                else:
                    raw_status = entry.get("status")
                    status_type = raw_status.get("type") if isinstance(raw_status, dict) else raw_status
                    value = {
                        "name": entry.get("name") or entry.get("preview") or thread_id,
                        "status": "processing" if status_type == "active" else "idle",
                        "connection": "not_loaded",
                        "queue_size": 0,
                    }
                self._apply_name(thread_id, value, summary=True)
                value.update({
                    "thread_id": thread_id,
                    "cwd": entry.get("cwd") or value.get("cwd"),
                    "project_id": entry.get("projectId") or value.get("project_id"),
                    "updated_at": entry.get("recencyAt") or entry.get("updatedAt") or entry.get("createdAt"),
                })
                if thread_id in errors:
                    value["connection"] = "error"
                    value["error"] = errors[thread_id]
                summaries.append(value)
            return summaries
        with self._lock:
            services = list(self._services_by_id.items())
        summaries: list[dict[str, Any]] = []
        for thread_id, service in services:
            if self._fixed_ids is not None and thread_id not in self._fixed_ids:
                continue
            value = deepcopy(service.summary())
            self._apply_name(thread_id, value, summary=True)
            value["thread_id"] = thread_id
            summaries.append(value)
        return summaries

    def project_summaries(self) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for session in self.session_summaries():
            cwd = str(session.get("cwd") or "").strip()
            project_id = str(session.get("project_id") or "").strip()
            key = project_key(cwd) or project_id or "unassigned"
            project = groups.get(key)
            if project is None:
                name = Path(cwd).name if cwd else "未分配项目"
                project = {"id": key, "name": name or cwd, "cwd": cwd, "sessions": []}
                project['original_name'] = project['name']
                if self.profiles and cwd:
                    try:
                        profile = self.profiles.get(key)
                        project.update(alias=profile['alias'], revision=profile['revision'],
                                       has_notice=bool(profile['notice_markdown'].strip()))
                        project['name'] = profile['alias'] or project['name']
                    except ValueError:
                        project['profile_error'] = True
                groups[key] = project
            project["sessions"].append(session)
        return list(groups.values())

    def project_profile(self, project_id, changes=None):
        if not self.profiles:
            raise ValueError('当前服务未启用项目资料')
        project = next((p for p in self.project_summaries()
                        if p['id'] == project_id and p['cwd']), None)
        if project is None:
            raise ValueError('指定项目不在共享列表中或没有工作目录')
        if changes is None:
            record = self.profiles.get(project_id)
        else:
            record = self.profiles.save(project_id, changes.get('alias'),
                                        changes.get('notice_markdown'), changes.get('revision'))
            self._broadcast()
        return dict(record, project_id=project_id, cwd=project['cwd'], original_name=project['original_name'])

    def refresh_catalog(self) -> None:
        if not self._catalog_mode:
            if self.tasks and hasattr(self.tasks.client, 'list_threads'):
                self._refresh_names(self.tasks.client.list_threads())
            return
        raw_threads = self._catalog_client.list_threads()
        mapped: dict[str, dict[str, Any]] = {}
        for raw in raw_threads:
            if not isinstance(raw, dict):
                continue
            thread_id = str(raw.get("id") or "").strip()
            if thread_id and thread_id not in mapped:
                mapped[thread_id] = dict(raw)
        with self._lock:
            if self._fixed_ids is not None:
                mapped = {sid: row for sid, row in mapped.items() if sid in self._fixed_ids}
            changed = mapped != self._catalog_by_id or self._catalog_error is not None
            self._catalog_by_id = mapped
            self._catalog_error = None
            if self._default_session_id not in mapped:
                self._default_session_id = next(iter(mapped), next(iter(self._added_by_id), None))
            stale_services = [
                (thread_id, service)
                for thread_id, service in self._services_by_id.items()
                if thread_id not in mapped and thread_id not in self._added_by_id
            ]
        removable: list[tuple[str, Any]] = []
        for thread_id, service in stale_services:
            try:
                summary = service.summary()
            except Exception:
                continue
            if summary.get("status") != "processing" and not int(summary.get("queue_size") or 0):
                removable.append((thread_id, service))
        close_services: list[Any] = []
        with self._lock:
            for thread_id, service in removable:
                if self._services_by_id.get(thread_id) is service and thread_id not in self._catalog_by_id:
                    close_services.append(self._services_by_id.pop(thread_id))
                    self._session_errors.pop(thread_id, None)
        for service in close_services:
            try:
                service.close()
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot close removed Session service: %s", type(exc).__name__)
        names_changed = self._refresh_names(raw_threads, broadcast=False)
        if changed or names_changed:
            self._broadcast()

    def _refresh_names(self, threads, *, broadcast=True):
        # Metadata only: never resume threads, reload turns or alter membership.
        with self._lock:
            shared = set(self.thread_ids)
            names = {sid: value for sid, value in self._thread_names.items() if sid in shared}
            for thread in threads:
                if not isinstance(thread, dict) or thread.get('id') not in shared:
                    continue
                if 'name' not in thread:
                    continue  # Incomplete metadata must not erase a known title.
                name = thread['name']
                if name is not None and not isinstance(name, str):
                    continue
                value = {'name': name}
                if isinstance(thread.get('preview'), str):
                    value['preview'] = thread['preview']
                names[thread['id']] = value
            changed = names != self._thread_names or self._catalog_error is not None
            self._thread_names = names
            self._catalog_error = None
        if changed and broadcast:
            self._broadcast()
        return changed

    def _apply_name(self, sid, target, *, summary=False):
        with self._lock:
            metadata = dict(self._thread_names.get(sid, {}))
        if metadata:
            if summary:
                target['name'] = metadata.get('name') or metadata.get('preview') or sid
            else:
                target.update(metadata)

    def _set_catalog_error(self, exc: Exception) -> None:
        message = f"无法刷新 Codex Session 目录：{exc}"
        with self._lock:
            changed = message != self._catalog_error
            self._catalog_error = message
        if self.logger:
            self.logger.warning("Cannot refresh Codex Session catalog: %s", type(exc).__name__)
        if changed:
            self._broadcast()

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self._refresh_seconds):
            try:
                self.refresh_catalog()
            except Exception as exc:
                self._set_catalog_error(exc)

    def submit(self, session_id: Any, text: str, images: list[dict[str, str]], source_ip: str, *, documents=None) -> str:
        with self._service_create_lock:
            service = self._service(session_id)[1]
            if documents:
                return service.submit(text, images, source_ip, documents=documents)
            return service.submit(text, images, source_ip)

    def cancel_queued(self, session_id: Any, message_id: str, source_ip: str) -> bool:
        return self._service(session_id)[1].cancel_queued(message_id, source_ip)

    def clear_queued(self, session_id: Any, source_ip: str) -> int:
        return self._service(session_id)[1].clear_queued(source_ip)

    def cancel(self, session_id: Any, source_ip: str) -> bool:
        return self._service(session_id)[1].cancel(source_ip)

    def release_session(self, session_id: Any, source_ip: str) -> bool:
        return self._service(session_id)[1].release_session(source_ip)

    def reconnect_session(self, session_id: Any, source_ip: str) -> bool:
        with self._service_create_lock:
            return self._service(session_id)[1].reconnect_session(source_ip)

    def resync(self, session_id: Any, source_ip: str) -> bool:
        return self._service(session_id)[1].resync(source_ip)

    def update_model_settings(
        self,
        session_id: Any,
        model: str,
        reasoning_effort: str,
        service_tier: str | None,
        source_ip: str,
    ) -> dict[str, str | None]:
        return self._service(session_id)[1].update_model_settings(
            model, reasoning_effort, service_tier, source_ip
        )

    def subscribe(self) -> queue.Queue[int]:
        subscriber: queue.Queue[int] = queue.Queue(maxsize=4)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[int]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _service_changed(self) -> None:
        self._broadcast()

    def _broadcast(self) -> None:
        with self._lock:
            self._version += 1
            version = self._version
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(version)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(version)
                except queue.Full:
                    pass

    def close(self) -> None:
        self._stop.set()
        if self.tasks:
            try:
                self.tasks.close()
            except Exception as exc:
                if self.logger:
                    self.logger.warning('Cannot close task metadata client: %s', type(exc).__name__)
        if self._catalog_mode:
            try:
                self._catalog_client.close()
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot close Session catalog client: %s", type(exc).__name__)
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=2)
        with self._lock:
            services = list(dict.fromkeys([*self._services, *self._services_by_id.values()]))
        for service in reversed(services):
            try:
                service.close()
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot close LAN Session service: %s", type(exc).__name__)
