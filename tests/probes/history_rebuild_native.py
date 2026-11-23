"""Opt-in native compatibility experiment; all data and provider traffic are local.

Run from repository root: python tests/probes/history_rebuild_native.py
No production session is accessed. This is NOT a history migration utility.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from uuid import uuid4

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lan_codex_share.jsonrpc import JsonRpcConnection


def row(kind, payload):
    return {'timestamp': '2026-11-20T00:00:00Z', 'type': kind, 'payload': payload}


def message(role, text):
    return {'type': 'message', 'role': role, 'content': [
        {'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}


def turn(index):
    tid = str(uuid4())
    return [
        row('event_msg', {'type': 'task_started', 'turn_id': tid, 'model_context_window': 200000}),
        row('response_item', message('user', f'PROBE_USER_{index}')),
        row('event_msg', {'type': 'user_message', 'message': f'PROBE_USER_{index}',
                          'images': [], 'local_images': [], 'text_elements': []}),
        row('response_item', dict(message('assistant', f'PROBE_ANSWER_{index}'), phase='final_answer')),
        row('event_msg', {'type': 'agent_message', 'message': f'PROBE_ANSWER_{index}', 'phase': 'final_answer'}),
        row('event_msg', {'type': 'task_complete', 'turn_id': tid, 'last_agent_message': f'PROBE_ANSWER_{index}'}),
    ]


@contextmanager
def native(home):
    executable = shutil.which('codex.cmd' if os.name == 'nt' else 'codex')
    if not executable:
        raise RuntimeError('Codex executable not installed')
    env = dict(os.environ, CODEX_HOME=str(home))
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
        env.pop(key, None)
    process = subprocess.Popen(
        [executable, 'app-server', '--stdio'], env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    rpc = JsonRpcConnection(process.stdout, process.stdin)
    rpc.start()
    try:
        rpc.request('initialize', {'clientInfo': {'name': 'history_rebuild_probe', 'version': '1'},
                                   'capabilities': {'experimentalApi': True}})
        rpc.notify('initialized', {})
        yield rpc
    finally:
        rpc.close()
        try:
            owned = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            owned = []
        for child in reversed(owned):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        _, alive = psutil.wait_procs(owned, timeout=5)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass


def run():
    captured = queue.Queue()

    class MockProvider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            captured.put(json.loads(body))
            # No real model, tools, or upstream request. Complete one synthetic turn.
            reply = message('assistant', 'PROBE_MOCK_DONE')
            reply.update(id='msg_probe', status='completed')
            events = [
                {'type': 'response.created', 'response': {'id': 'resp_probe', 'status': 'in_progress', 'output': []}},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': reply},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': reply},
                {'type': 'response.completed', 'response': {'id': 'resp_probe', 'status': 'completed', 'output': [reply],
                  'usage': {'input_tokens': 10, 'output_tokens': 1, 'total_tokens': 11}}},
            ]
            data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), MockProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = Path(tempfile.mkdtemp(prefix='codex-history-rebuild-probe-'))
    home = base / 'home'
    home.mkdir()
    (home / 'config.toml').write_text(
        'model = "probe-local"\nmodel_provider = "probe"\n'
        '[model_providers.probe]\nname = "Local isolated probe"\n'
        f'base_url = "http://127.0.0.1:{server.server_port}/v1"\n'
        'wire_api = "responses"\nrequires_openai_auth = false\n'
        'request_max_retries = 0\nstream_max_retries = 0\n', encoding='utf-8')
    report = {'fixture_directory': str(base)}
    try:
        with native(home) as rpc:
            created = rpc.request('thread/start', {'cwd': str(base), 'historyMode': 'paginated',
                                                   'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']
        sid, path = created['id'], Path(created['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = row('session_meta', {'id': sid, 'timestamp': '2026-11-20T00:00:00Z',
            'cwd': str(base), 'originator': 'codex_cli_rs', 'cli_version': '0.1.0',
            'source': 'cli', 'model_provider': 'probe'})
        groups = [turn(i) for i in range(3)]
        def compact(n):
            return row('compacted', {'message': f'PROBE_STALE_SUMMARY_{n}',
                'replacement_history': [message('user', f'PROBE_STALE_SUMMARY_{n}')],
                'window_number': n, 'first_window_id': 'probe-first',
                'previous_window_id': 'probe-first', 'window_id': f'probe-{n}'})
        baseline = [meta] + groups[0] + groups[1] + [compact(1), compact(2)] + groups[2]
        rebuilt = [meta] + groups[0] + groups[2]

        def write(rows):
            path.write_text(''.join(json.dumps(item) + '\n' for item in rows), encoding='utf-8')

        def check(label, rows, expected, observer=None):
            write(rows)
            with native(home) as rpc:
                thread = rpc.request('thread/resume', {'threadId': sid, 'path': str(path),
                    'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']
                pages = rpc.request('thread/turns/list', {'threadId': sid, 'itemsView': 'full', 'limit': 100})
                visible = json.dumps(pages)
                assert thread['id'] == sid
                for index in expected:
                    assert f'PROBE_USER_{index}' in visible, (label, index)
                if label == 'rebuilt':
                    assert 'PROBE_USER_1' not in visible
                done = threading.Event()
                rpc.add_notification_handler(lambda method, params: done.set() if method == 'turn/completed' else None)
                rpc.request('turn/start', {'threadId': sid, 'input': [{'type': 'text', 'text': 'PROBE_NEXT', 'text_elements': []}]})
                request = captured.get(timeout=25)
                assert done.wait(20), 'Mock turn did not complete'
                contents = json.dumps(request.get('input', []))
                if label == 'baseline':
                    assert 'PROBE_STALE_SUMMARY_2' in contents, 'Compaction fixture was not restored'
                else:
                    assert 'PROBE_STALE_SUMMARY' not in contents
                    assert 'PROBE_USER_1' not in contents and 'PROBE_ANSWER_1' not in contents
                    for index in expected:
                        assert f'PROBE_USER_{index}' in contents and f'PROBE_ANSWER_{index}' in contents
                    rpc.request('thread/archive', {'threadId': sid})
                    rpc.request('thread/unarchive', {'threadId': sid})
                report[label] = {'same_id': True, 'native_turn_count': len(pages['data']),
                                 'next_context_verified': True, 'mock_turn_completed': True}
                if observer is not None:
                    fresh = observer.request('thread/turns/list', {'threadId': sid, 'itemsView': 'full', 'limit': 100})
                    encoded = json.dumps(fresh)
                    assert 'PROBE_USER_1' not in encoded, 'Long-lived observer retained deleted turn'
                    assert 'PROBE_USER_0' in encoded and 'PROBE_USER_2' in encoded
                    report['live_observer_refreshed'] = True

        check('baseline', baseline, [0, 1, 2])
        with native(home) as observer:
            before = observer.request('thread/turns/list', {'threadId': sid, 'itemsView': 'full', 'limit': 100})
            assert 'PROBE_USER_1' in json.dumps(before)
            check('rebuilt', rebuilt, [0, 2], observer)
        # Exercise the production backup/replace/readback transaction on supported history.
        from lan_codex_share.history_edit import apply_history_edit, native_writer_guard
        plain = [meta] + groups[0] + groups[1] + groups[2]
        write(plain)
        with native(home) as reader:
            def verify_native(_path, _sid):
                value = reader.request('thread/read', {'threadId': _sid, 'includeTurns': True})['thread']
                assert {t['id'] for t in value['turns']} == {groups[i][0]['payload']['turn_id'] for i in (0, 2)}
            result = apply_history_edit(path, home, sid, [groups[1][0]['payload']['turn_id']],
                writer_guard=native_writer_guard(home, sid), verify=verify_native)
            assert result['deleted_turns'] == 1 and Path(result['backup']).is_file()
            report['production_transaction_native_readback'] = True
        # A separate synthetic native thread avoids overwriting a fixture with a
        # longer unrelated log after its projection offset has already advanced.
        with native(home) as rpc:
            created = rpc.request('thread/start', {'cwd': str(base), 'historyMode': 'paginated',
                'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']
        sid, path = created['id'], Path(created['path']); path.parent.mkdir(parents=True, exist_ok=True)
        process_group = list(groups[0])
        process_group[-1:-1] = [row('response_item', {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': 'PROBE_PROCESS'}], 'content': None, 'encrypted_content': None}),
                               row('event_msg', {'type': 'agent_reasoning', 'text': 'PROBE_PROCESS'})]
        write([dict(meta, payload=dict(meta['payload'], id=sid))] + process_group + groups[1] + groups[2])
        with native(home) as reader:
            before = reader.request('thread/read', {'threadId': sid, 'includeTurns': True})['thread']
            records = []
            expected_items = []
            for t in before['turns']:
                for i in t['items']:
                    process = t['id'] == groups[0][0]['payload']['turn_id'] and i['type'] not in {'userMessage', 'agentMessage'}
                    chosen = process or (t['id'] == groups[1][0]['payload']['turn_id'] and i['type'] == 'agentMessage') or (t['id'] == groups[2][0]['payload']['turn_id'] and i['type'] == 'userMessage')
                    if chosen: records.append({'turn_id': t['id'], 'item_id': '__process__' if process else i['id'], '_native': i})
                    else: expected_items.append((t['id'], {k: v for k, v in i.items() if k != 'id'}))
            assert len(records) == 3
            def verify_messages(_path, _sid):
                value = reader.request('thread/read', {'threadId': _sid, 'includeTurns': True})['thread']
                actual_items = [(t['id'], {k: v for k, v in i.items() if k != 'id'}) for t in value['turns'] for i in t['items']]
                assert actual_items == expected_items
            apply_history_edit(path, home, sid, [], selected_messages=records,
                writer_guard=native_writer_guard(home, sid), verify=verify_messages)
        with native(home) as rpc:
            rpc.request('thread/resume', {'threadId': sid, 'path': str(path), 'approvalPolicy': 'never', 'sandbox': 'read-only'})
            done = threading.Event()
            rpc.add_notification_handler(lambda method, params: done.set() if method == 'turn/completed' else None)
            rpc.request('turn/start', {'threadId': sid, 'input': [{'type': 'text', 'text': 'PROBE_NEXT', 'text_elements': []}]})
            request = captured.get(timeout=25); assert done.wait(20)
            contents = json.dumps(request.get('input', []))
            assert 'PROBE_ANSWER_1' not in contents and 'PROBE_USER_2' not in contents
            assert 'PROBE_PROCESS' not in contents
            assert 'PROBE_USER_1' in contents and 'PROBE_ANSWER_2' in contents
        report['independent_messages_native_and_next_context'] = True
        with native(home) as rpc:
            created = rpc.request('thread/start', {'cwd': str(base), 'historyMode': 'paginated',
                'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']
        sid, path = created['id'], Path(created['path']); path.parent.mkdir(parents=True, exist_ok=True)
        write([dict(meta, payload=dict(meta['payload'], id=sid))] + process_group + groups[1] + groups[2])
        target = groups[0][0]['payload']['turn_id']
        with native(home) as reader:
            before = reader.request('thread/read', {'threadId': sid, 'includeTurns': True})['thread']
            expected_items = [(t['id'], {k: v for k, v in i.items() if k != 'id'})
                for t in before['turns'] for i in t['items'] if t['id'] != target or i['type'] == 'userMessage']
            result = apply_history_edit(path, home, sid, [],
                selected_messages=[{'turn_id': target, 'item_id': '__response__'}],
                writer_guard=native_writer_guard(home, sid), verify=verify_messages)
            assert result['deleted_messages'] == 1
        with native(home) as rpc:
            rpc.request('thread/resume', {'threadId': sid, 'path': str(path), 'approvalPolicy': 'never', 'sandbox': 'read-only'})
            done = threading.Event()
            rpc.add_notification_handler(lambda method, params: done.set() if method == 'turn/completed' else None)
            rpc.request('turn/start', {'threadId': sid, 'input': [{'type': 'text', 'text': 'PROBE_GROUP_NEXT', 'text_elements': []}]})
            request = captured.get(timeout=25); assert done.wait(20)
            contents = json.dumps(request.get('input', []))
            assert 'PROBE_PROCESS' not in contents and 'PROBE_ANSWER_0' not in contents
            assert 'PROBE_USER_0' in contents and 'PROBE_ANSWER_1' in contents
        report['grouped_response_single_selection_native_and_next_context'] = True
        # Production job, including paged native verification, on >100 stale
        # encrypted compactions. No real CODEX_HOME or upstream model is used.
        from types import SimpleNamespace as NS
        from lan_codex_share.history_edit import HistoryEditor
        from lan_codex_share.history_rebuild import digest_file
        from lan_codex_share.history_native import native_history_signature
        with native(home) as rpc:
            created = rpc.request('thread/start', {'cwd': str(base), 'historyMode': 'paginated',
                'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']
        sid, path = created['id'], Path(created['path']); path.parent.mkdir(parents=True, exist_ok=True)
        long_groups = [turn(i) for i in range(45)]
        stale = [dict(compact(i), payload=dict(compact(i)['payload'], replacement_history=[
            message('user', 'PROBE_DELETED_IN_OLD_SUMMARY'),
            {'type': 'compaction', 'encrypted_content': 'PROBE_OLD_OPAQUE_' + str(i)}])) for i in range(120)]
        long_rows = [dict(meta, payload=dict(meta['payload'], id=sid))]
        for i, group in enumerate(long_groups):
            group[1]['payload']['content'][0]['text'] += ('KEEP_PAYLOAD_' + str(i) + ' ') * 1500
            group[2]['payload']['message'] = group[1]['payload']['content'][0]['text']
            long_rows.extend(group)
            long_rows.extend(stale[i * 3:(i + 1) * 3])
        write(long_rows)
        with native(home) as rpc:
            client = NS(start=lambda: None, rpc=rpc,
                read_thread_metadata=lambda sid: rpc.request('thread/read', {'threadId': sid, 'includeTurns': False})['thread'])
            target = long_groups[0][0]['payload']['turn_id']
            page = rpc.request('thread/turns/list', {'threadId': sid, 'itemsView': 'full', 'limit': 100})
            user = next(item for t in page['data'] if t['id'] == target for item in t['items'] if item['type'] == 'userMessage')
            selection = [{'turn_id': target, 'item_id': '__response__'}, {'turn_id': target, 'item_id': user['id']}]
            expected, _, _ = native_history_signature(client, sid, records=selection)
            projected = []
            service = NS(_queued_lock=threading.RLock(), release_session=lambda _: None,
                projection=NS(replace_thread=projected.append, set_connection=lambda _: None), _broadcast=lambda: None)
            hub = NS(resolve_session_id=lambda value: value, _service_create_lock=threading.RLock(), _service=lambda _: (sid, service))
            editor = HistoryEditor(hub, NS(home=home, tasks=NS(client=client)))
            inspection = editor.listing(sid)
            assert inspection['compactions'] == 120 and inspection['blocked_reason'] is None
            editor._jobs['long'] = {'session_id': sid}; editor._busy.add(sid)
            editor._run('long', sid, selection, inspection['revision'], 'probe', True)
            job = editor.status(sid, 'long')
            assert job['state'] == 'done', job
            assert job['result']['deleted_messages'] == 2 and job['result']['context_reset']
            assert job['result']['context_bytes'] <= 32768 and Path(job['result']['backup']).is_file()
            actual, _, _ = native_history_signature(client, sid)
            assert expected == actual
            assert projected and projected[0]['id'] == sid
        with native(home) as rpc:
            rpc.request('thread/resume', {'threadId': sid, 'path': str(path), 'approvalPolicy': 'never', 'sandbox': 'read-only'})
            done = threading.Event()
            rpc.add_notification_handler(lambda method, params: done.set() if method == 'turn/completed' else None)
            rpc.request('turn/start', {'threadId': sid, 'input': [{'type': 'text', 'text': 'PROBE_LONG_NEXT', 'text_elements': []}]})
            request = captured.get(timeout=25); assert done.wait(20)
            contents = json.dumps(request.get('input', []))
            assert 'PROBE_DELETED_IN_OLD_SUMMARY' not in contents and 'PROBE_OLD_OPAQUE_' not in contents
            assert 'PROBE_USER_0' not in contents and 'PROBE_ANSWER_0' not in contents
            assert 'PROBE_USER_44' in contents and 'PROBE_ANSWER_44' in contents
            assert len(contents.encode()) < 100000
        report['long_production_job_120_compactions_paged_native_and_bounded_next_context'] = True
        if os.name == 'nt':
            import msvcrt
            from lan_codex_share.jsonrpc import JsonRpcError
            with (home / 'thread-writer-locks' / (sid + '.lock')).open('a+b') as lock:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    with native(home) as rpc:
                        try:
                            rpc.request('thread/resume', {'threadId': sid, 'path': str(path)}, timeout=10)
                        except JsonRpcError as exc:
                            assert 'lock' in str(exc).lower() or 'writer' in str(exc).lower() or 'another' in str(exc).lower(), str(exc)
                            report['edit_lock_excludes_native_writer'] = True
                        else:
                            raise AssertionError('Native resume bypassed editing lock')
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        server.shutdown()
        server.server_close()
        (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    run()
