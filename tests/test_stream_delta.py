from copy import deepcopy
import http.client
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from lan_codex_share.stream_delta import SnapshotDelta
from tests.test_history_pagination import history_server  # pytest fixture
from tests.test_lan_web import request


def snapshot(text='hello', epoch='a'):
    return {'thread_id': 's', 'version': 1, 'pending': [], 'history': {'epoch': epoch},
            'thread': {'id': 's', 'turns': [{'id': 't', 'history_revision': 0, 'activity_count': 0,
                'items': [{'id': 'u', 'type': 'userMessage', 'text': 'question'},
                          {'id': 'a', 'type': 'agentMessage', 'text': text}]}]}}


def test_delta_only_transfers_new_text_and_handles_corrections():
    stream = SnapshotDelta()
    first = snapshot('a' * 100000)
    assert stream.next(first)['event'] == 'snapshot'
    assert stream.next(deepcopy(first)) is None
    next_value = snapshot('a' * 100000 + '新增字符')
    frame = stream.next(next_value)
    assert frame['event'] == 'delta'
    assert len(json.dumps(frame)) < 500
    assert frame['data']['base'] == 1
    assert frame['data']['turns'][0]['items'] == [{'id': 'a', 'append': '新增字符'}]
    corrected = stream.next(snapshot('corrected'))
    assert corrected['data']['turns'][0]['items'][0]['replace']['text'] == 'corrected'
    assert stream.next(snapshot('new', epoch='b'))['event'] == 'snapshot'


def test_delta_carries_metadata_item_removal_and_new_turns():
    stream = SnapshotDelta()
    old = snapshot()
    old['last_error'] = 'old'
    stream.next(old)
    new = snapshot()
    new['pending'] = [{'id': 'queued'}]
    new['thread']['name'] = 'renamed'
    new['thread']['turns'][0]['items'].pop(0)
    new['thread']['turns'][0]['activity_count'] = 1
    new['thread']['turns'].append({'id': 'second', 'items': []})
    frame = stream.next(new)['data']
    assert frame['removed'] == ['last_error']
    assert frame['fields']['pending'] == [{'id': 'queued'}]
    assert frame['thread_fields'] == {'name': 'renamed'}
    assert frame['order'] == ['t', 'second']
    assert frame['turns'][0]['order'] == ['a']
    assert frame['turns'][1]['replace']['id'] == 'second'


def test_python_frames_roundtrip_through_real_browser_reducer():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js required')
    values = [snapshot(), snapshot('hello 😀\n中文')]
    third = deepcopy(values[-1])
    third['pending'] = [{'id': 'queued'}]
    third['thread']['turns'][0]['items'][1]['text'] = 'corrected'
    third['thread']['turns'][0]['error'] = 'test error'
    values.append(third)
    fourth = deepcopy(third)
    del fourth['thread']['turns'][0]['error']
    fourth['thread']['turns'][0]['items'].pop(0)
    fourth['thread']['turns'].append({'id': 'new', 'items': []})
    values.extend([fourth, snapshot('resync', epoch='new')])
    stream = SnapshotDelta()
    frames = [stream.next(value) for value in values]
    script = """
const fs = require('node:fs'), assert = require('node:assert/strict');
const {StreamSnapshot} = require(process.argv[1]);
const {frames, values} = JSON.parse(fs.readFileSync(0, 'utf8'));
const state = new StreamSnapshot();
frames.forEach((frame, index) => assert.deepEqual(state.apply(frame.event, frame.data), values[index]));
"""
    module = Path(__file__).parents[1] / 'lan_codex_share/web/realtime.js'
    result = subprocess.run([node, '-e', script, str(module)],
        input=json.dumps({'frames': frames, 'values': values}), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def read_event(response):
    event = None
    while True:
        line = response.readline()
        if line.startswith(b'event: '):
            event = line.decode().strip()[7:]
        if line.startswith(b'data: '):
            return event, json.loads(line[6:])
        if not line:
            raise AssertionError('SSE closed before event')


def test_delta_stream_has_auth_and_selection_checks_then_pushes_without_http_refresh(history_server):
    app, hub, server = history_server
    route = '/api/events?mode=delta&session_id=history-session'
    assert request(server, 'GET', route)[0] == 401
    cookie = {'Cookie': f'lan_codex_auth={app.authenticate(app.password, "test")}'}
    assert request(server, 'GET', route.replace('history-session', 'private'), headers=cookie)[0] == 400
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
    try:
        connection.request('GET', route, headers=cookie)
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader('Cache-Control') == 'no-store, no-transform'
        event, first = read_event(response)
        assert event == 'snapshot'
        assert len(first['snapshot']['thread']['turns']) == 20
        hub._services[0].projection.apply_notification('item/agentMessage/delta', {
            'turnId': 't-99', 'itemId': 'a-99', 'delta': ' pushed',
        })
        event, data = read_event(response)
        assert event == 'delta'
        assert any(item.get('append') == ' pushed' for turn in data['turns'] for item in turn.get('items', []))
    finally:
        connection.close()
        server.stopping.set()
