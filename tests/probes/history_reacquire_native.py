"""Opt-in native writer regression; only temporary sessions, no model requests."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.probes.history_rebuild_native import native, row, turn, message
from lan_codex_share.history_edit import HistoryEditor
from lan_codex_share.jsonrpc import JsonRpcError
from lan_codex_share.lan_service import LanChatService
from lan_codex_share.session_projection import SessionProjection


def run():
    base = Path(tempfile.mkdtemp(prefix='codex-history-reacquire-'))
    home = base / 'home'
    home.mkdir()
    (home / 'config.toml').write_text('model="probe-local"\nmodel_provider="probe"\n'
        '[model_providers.probe]\nname="Offline diagnostic"\n'
        'base_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\n', encoding='utf-8')
    with native(home) as rpc:
        created = rpc.request('thread/start', {'cwd': str(base), 'historyMode': 'paginated',
            'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']
    sid, path = created['id'], Path(created['path'])
    rows = [row('session_meta', {'id': sid, 'timestamp': '2026-11-20T00:00:00Z', 'cwd': str(base),
        'originator': 'codex_cli_rs', 'cli_version': '0.1.0', 'source': 'cli', 'model_provider': 'probe'})]
    groups = [turn(i) for i in range(30)]
    for i, group in enumerate(groups):
        rows.extend(group)
        for n in range(4):
            rows.append(row('compacted', {'message': 'OLD_SUMMARY', 'replacement_history': [message('user', 'OLD_SUMMARY')]}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(item) + '\n' for item in rows), encoding='utf-8')

    class Writer:
        def __init__(self):
            self.context = self.rpc = None
            self.reads = []

        def read_thread(self, include_turns=True):
            self.reads.append(include_turns)
            if self.context is None:
                self.context = native(home)
                self.rpc = self.context.__enter__()
            self.rpc.request('thread/resume', {'threadId': sid, 'path': str(path),
                'approvalPolicy': 'never', 'sandbox': 'read-only'})
            return self.rpc.request('thread/read', {'threadId': sid, 'includeTurns': include_turns})['thread']

        def close(self):
            if self.context:
                self.context.__exit__(None, None, None)
                self.context = self.rpc = None

    writer = Writer()
    service = LanChatService(writer, SessionProjection())
    service.thread_id = sid
    report = {'directory': str(base), 'session_id': sid}
    try:
        service.projection.replace_thread(writer.read_thread(False))
        service.projection.set_connection('connected')
        with native(home) as rpc:
            client = NS(start=lambda: None, rpc=rpc,
                read_thread_metadata=lambda _: rpc.request('thread/read', {'threadId': sid, 'includeTurns': False})['thread'])
            target = groups[0][0]['payload']['turn_id']
            page = rpc.request('thread/turns/list', {'threadId': sid, 'itemsView': 'full', 'limit': 100})
            user = next(i for t in page['data'] if t['id'] == target for i in t['items'] if i['type'] == 'userMessage')
            selection = [{'turn_id': target, 'item_id': user['id']}, {'turn_id': target, 'item_id': '__response__'}]
            hub = NS(resolve_session_id=lambda value: value, _service_create_lock=threading.RLock(), _service=lambda _: (sid, service))
            editor = HistoryEditor(hub, NS(home=home, tasks=NS(client=client)))
            inspection = editor.listing(sid)
            assert inspection['compactions'] == 120
            editor._jobs['edit'] = {'session_id': sid}
            editor._busy.add(sid)
            editor._run('edit', sid, selection, inspection['revision'], 'probe', True)
            job = editor.status(sid, 'edit')
            assert job['state'] == 'done' and job['result']['connection'] == 'connected', job
            assert job['result']['deleted_messages'] == 2
            assert writer.reads == [False, False], writer.reads
            assert service.snapshot()['connection'] == 'connected'
        with native(home) as competitor:
            try:
                competitor.request('thread/resume', {'threadId': sid, 'path': str(path)}, timeout=10)
            except JsonRpcError as exc:
                assert any(word in str(exc).lower() for word in ('writer', 'lock', 'another')), str(exc)
            else:
                raise AssertionError('Second native client acquired the edited session')
        report['same_id_reacquired_and_second_writer_blocked'] = True
        service.release_session('probe')
        with native(home) as competitor:
            resumed = competitor.request('thread/resume', {'threadId': sid, 'path': str(path)}, timeout=10)
            assert resumed['thread']['id'] == sid
        report['explicit_release_allows_other_client'] = True
        report['status'] = 'passed'
    finally:
        service.close()
        (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    run()
