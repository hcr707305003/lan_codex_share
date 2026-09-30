import queue

import pytest

from lan_codex_share.session_hub import LanSessionHub


class FakeSessionService:
    def __init__(self, thread_id, name):
        self.thread_id = thread_id
        self.name = name
        self.handlers = []
        self.calls = []
        self.closed = False
        self.released = []
        self.reconnected = []

    def add_change_handler(self, handler):
        self.handlers.append(handler)

    def start(self):
        return None

    def summary(self):
        return {
            "thread_id": self.thread_id, "name": self.name, "status": "idle",
            "connection": "connected", "queue_size": 0,
        }

    def snapshot(self):
        return {
            "thread_id": self.thread_id, "status": "idle", "connection": "connected",
            "queue_size": 0, "version": 1, "thread": {"id": self.thread_id, "turns": []},
            "pending": [],
        }

    def submit(self, text, images, source_ip):
        self.calls.append((text, images, source_ip))
        return f"message-{self.thread_id}"

    def release_session(self, source_ip):
        self.released.append(source_ip)
        return True

    def reconnect_session(self, source_ip):
        self.reconnected.append(source_ip)
        return True

    def close(self):
        self.closed = True


def test_hub_selects_and_routes_independent_sessions():
    first = FakeSessionService("session-a", "Alpha")
    second = FakeSessionService("session-b", "Beta")
    hub = LanSessionHub([first, second])
    hub.start()
    try:
        snapshot = hub.snapshot("session-b")

        assert snapshot["selected_session_id"] == "session-b"
        assert [item["thread_id"] for item in snapshot["sessions"]] == ["session-a", "session-b"]
        assert hub.submit("session-b", "hello", [], "192.168.1.2") == "message-session-b"
        assert first.calls == []
        assert second.calls == [("hello", [], "192.168.1.2")]
        with pytest.raises(ValueError, match="共享列表"):
            hub.snapshot("not-shared")
    finally:
        hub.close()
    assert first.closed and second.closed


def test_static_hub_can_register_lazy_session_without_expanding_preview_roots(tmp_path):
    first = FakeSessionService('session-a', 'Alpha')
    added = []
    hub = LanSessionHub([first])
    hub.configure_tasks(None, lambda metadata: added.append(FakeSessionService(metadata['id'], metadata['name'])) or added[-1])
    hub.start()
    try:
        hub.register_session({'id': 'session-b', 'cwd': str(tmp_path), 'name': 'Beta'})
        assert hub.thread_ids == ('session-a', 'session-b')
        assert hub.snapshot('session-a')['sessions'][1]['connection'] == 'not_loaded'
        assert added == []
        assert hub.preview_roots == ()
        assert hub.snapshot('session-b')['thread_id'] == 'session-b'
        assert len(added) == 1
        hub.snapshot('session-b')
        assert len(added) == 1
    finally:
        hub.close()
    assert added[0].closed


def test_project_groups_use_directory_identity_not_mixed_project_ids(tmp_path):
    hub = LanSessionHub([FakeSessionService('a', 'A')])
    hub.start()
    try:
        hub.register_session({'id': 'b', 'cwd': str(tmp_path), 'projectId': 'project', 'name': 'B'})
        hub.register_session({'id': 'c', 'cwd': str(tmp_path / 'child' / '..'), 'name': 'C'})
        project = next(p for p in hub.project_summaries() if len(p['sessions']) == 2)
        assert [s['thread_id'] for s in project['sessions']] == ['b', 'c']
    finally:
        hub.close()


def test_hub_fans_out_session_updates():
    service = FakeSessionService("session-a", "Alpha")
    hub = LanSessionHub([service])
    hub.start()
    subscriber = hub.subscribe()
    try:
        for handler in service.handlers:
            handler()
        assert isinstance(subscriber.get(timeout=0.2), int)
    except queue.Empty as exc:
        raise AssertionError("hub did not broadcast the session update") from exc
    finally:
        hub.unsubscribe(subscriber)
        hub.close()


def test_hub_routes_release_and_reconnect_to_target_session():
    first = FakeSessionService("session-a", "Alpha")
    second = FakeSessionService("session-b", "Beta")
    hub = LanSessionHub([first, second])
    hub.start()
    try:
        assert hub.release_session("session-b", "192.168.1.4")
        assert hub.reconnect_session("session-b", "192.168.1.4")
        assert first.released == []
        assert second.released == ["192.168.1.4"]
        assert second.reconnected == ["192.168.1.4"]
    finally:
        hub.close()


class FakeCatalogClient:
    def __init__(self, threads):
        self.threads = list(threads)
        self.error = None
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def list_threads(self):
        if self.error:
            raise self.error
        return list(self.threads)

    def close(self):
        self.closed = True


def catalog_thread(thread_id, cwd, project_id, name):
    return {
        "id": thread_id,
        "cwd": str(cwd),
        "projectId": project_id,
        "name": name,
        "status": {"type": "notLoaded"},
        "updatedAt": 10,
    }


def test_rename_updates_loaded_and_unloaded_sessions_without_reloading_history(tmp_path):
    catalog = FakeCatalogClient([
        catalog_thread('a', tmp_path, 'project', 'Old A'),
        catalog_thread('b', tmp_path, 'project', 'Old B'),
    ])
    created = []
    def factory(row):
        service = FakeSessionService(row['id'], row['name'])
        created.append(service)
        return service
    hub = LanSessionHub(catalog_client=catalog, service_factory=factory, refresh_seconds=3600)
    hub.start()
    try:
        original = hub.snapshot('a')
        from lan_codex_share.stream_delta import SnapshotDelta
        stream = SnapshotDelta()
        stream.next(original)
        # Added entries must not mask newer catalog names either.
        hub.register_session(catalog.threads[0])
        browsers = [hub.subscribe(), hub.subscribe()]
        catalog.threads[0]['name'] = 'New A'
        catalog.threads[1]['name'] = 'New B'
        hub.refresh_catalog()
        for browser in browsers:
            browser.get_nowait()
        updated = hub.snapshot('a')
        assert updated['thread']['name'] == 'New A'
        assert [s['name'] for s in updated['sessions']] == ['New A', 'New B']
        assert [s['name'] for s in updated['projects'][0]['sessions']] == ['New A', 'New B']
        assert updated['thread']['turns'] == original['thread']['turns']
        delta = stream.next(updated)
        assert delta['event'] == 'delta'
        assert delta['data']['thread_fields']['name'] == 'New A'
        assert delta['data']['turns'] == []
        assert len(created) == 1 and not created[0].closed
        assert created[0].name == 'Old A'  # metadata overlay, no service restart.
        hub.refresh_catalog()
        for browser in browsers:
            with pytest.raises(queue.Empty):
                browser.get_nowait()
    finally:
        hub.close()


def test_selected_sessions_poll_names_and_keep_membership():
    from types import SimpleNamespace
    service = FakeSessionService('a', 'Old')
    catalog = FakeCatalogClient([{'id': 'a', 'name': 'New'}, {'id': 'outside', 'name': 'Hidden'}])
    hub = LanSessionHub([service], refresh_seconds=.1)
    hub.tasks = SimpleNamespace(client=catalog, restore=lambda: None, close=lambda: None)
    updates = hub.subscribe()
    hub.start()
    try:
        updates.get(timeout=2)  # startup
        updates.get(timeout=2)  # background metadata refresh
        assert hub.snapshot('a')['thread']['name'] == 'New'
        assert hub.session_summaries()[0]['name'] == 'New'
        assert hub.thread_ids == ('a',)
        assert 'outside' not in hub._thread_names
    finally:
        hub.close()


def test_name_removal_and_failed_refresh_keep_history_and_last_good_name():
    from types import SimpleNamespace
    hub = LanSessionHub([FakeSessionService('a', 'Old')], refresh_seconds=3600)
    hub.start()
    catalog = FakeCatalogClient([{'id': 'a', 'name': 'New'}])
    hub.tasks = SimpleNamespace(client=catalog, close=lambda: None)
    try:
        hub.refresh_catalog()
        catalog.error = ValueError('offline')
        with pytest.raises(ValueError):
            hub.refresh_catalog()
        assert hub.snapshot('a')['thread']['name'] == 'New'
        catalog.error = None
        catalog.threads = [{'id': 'a', 'name': None, 'preview': 'First message'}]
        hub.refresh_catalog()
        assert hub.snapshot('a')['thread']['name'] is None
        assert hub.session_summaries()[0]['name'] == 'First message'
        hub._refresh_names([{'id': 'a'}])
        assert hub.session_summaries()[0]['name'] == 'First message'
    finally:
        hub.close()


def test_catalog_hub_groups_projects_and_loads_sessions_lazily(tmp_path):
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    project_a.mkdir()
    project_b.mkdir()
    catalog = FakeCatalogClient([
        catalog_thread("session-a", project_a, "project-a", "Alpha one"),
        catalog_thread("session-b", project_a, "project-a", "Alpha two"),
        catalog_thread("session-c", project_b, None, "Beta one"),
    ])
    created = []

    def factory(metadata):
        created.append(metadata["id"])
        return FakeSessionService(metadata["id"], metadata["name"])

    hub = LanSessionHub(
        catalog_client=catalog,
        service_factory=factory,
        refresh_seconds=3600,
    )
    hub.start()
    try:
        assert catalog.started
        assert created == []
        assert hub.preview_roots == (project_a.resolve(), project_b.resolve())

        snapshot = hub.snapshot("session-b")

        assert created == ["session-b"]
        assert snapshot["catalog_mode"] is True
        assert snapshot["selected_session_id"] == "session-b"
        assert [project["name"] for project in snapshot["projects"]] == ["alpha", "beta"]
        assert [item["thread_id"] for item in snapshot["projects"][0]["sessions"]] == ["session-a", "session-b"]
        assert hub.snapshot("session-b")["thread_id"] == "session-b"
        assert created == ["session-b"]
    finally:
        hub.close()
    assert catalog.closed


def test_catalog_hub_refreshes_directory_without_loading_new_session(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = FakeCatalogClient([catalog_thread("session-a", project, "project", "One")])
    created = []
    hub = LanSessionHub(
        catalog_client=catalog,
        service_factory=lambda metadata: created.append(metadata["id"]) or FakeSessionService(metadata["id"], metadata["name"]),
        refresh_seconds=3600,
    )
    hub.start()
    try:
        catalog.threads.append(catalog_thread("session-b", project, "project", "Two"))
        hub.refresh_catalog()

        assert hub.thread_ids == ("session-a", "session-b")
        assert created == []
    finally:
        hub.close()


def test_catalog_hub_isolates_session_load_failures(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = FakeCatalogClient([
        catalog_thread("broken", project, "project", "Broken"),
        catalog_thread("working", project, "project", "Working"),
    ])

    def factory(metadata):
        if metadata["id"] == "broken":
            raise RuntimeError("cannot resume")
        return FakeSessionService(metadata["id"], metadata["name"])

    hub = LanSessionHub(catalog_client=catalog, service_factory=factory, refresh_seconds=3600)
    hub.start()
    try:
        with pytest.raises(ValueError, match="无法加载 Session"):
            hub.snapshot("broken")
        assert hub.snapshot("working")["thread_id"] == "working"
        broken = next(item for item in hub.session_summaries() if item["thread_id"] == "broken")
        assert broken["connection"] == "error"
    finally:
        hub.close()


def test_catalog_hub_returns_empty_snapshot_when_no_sessions():
    catalog = FakeCatalogClient([])
    hub = LanSessionHub(
        catalog_client=catalog,
        service_factory=lambda metadata: FakeSessionService(metadata["id"], metadata["id"]),
        refresh_seconds=3600,
    )
    hub.start()
    try:
        snapshot = hub.snapshot()
        assert snapshot["catalog_mode"] is True
        assert snapshot["sessions"] == []
        assert snapshot["projects"] == []
        assert snapshot["selected_session_id"] is None
        assert snapshot["thread"]["turns"] == []
    finally:
        hub.close()


def test_catalog_hub_closes_idle_service_removed_from_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = FakeCatalogClient([catalog_thread("session-a", project, "project", "One")])
    service = FakeSessionService("session-a", "One")
    hub = LanSessionHub(
        catalog_client=catalog,
        service_factory=lambda metadata: service,
        refresh_seconds=3600,
    )
    hub.start()
    try:
        hub.snapshot("session-a")
        catalog.threads = []
        hub.refresh_catalog()

        assert hub.thread_ids == ()
        assert service.closed
    finally:
        hub.close()


def test_catalog_hub_exposes_initial_refresh_error_and_recovers(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = FakeCatalogClient([])
    catalog.error = RuntimeError("catalog unavailable")
    hub = LanSessionHub(
        catalog_client=catalog,
        service_factory=lambda metadata: FakeSessionService(metadata["id"], metadata["id"]),
        refresh_seconds=3600,
    )
    hub.start()
    try:
        failed = hub.snapshot()
        assert "无法刷新" in failed["catalog_error"]

        catalog.error = None
        catalog.threads = [catalog_thread("session-a", project, "project", "One")]
        hub.refresh_catalog()

        assert hub.thread_ids == ("session-a",)
        assert hub.snapshot("session-a")["catalog_error"] is None
    finally:
        hub.close()
