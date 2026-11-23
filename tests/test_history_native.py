from types import SimpleNamespace as NS
import pytest
from lan_codex_share.history_native import native_history_signature


def client(pages):
    calls = []
    def request(method, params, **kwargs):
        assert method == 'thread/turns/list' and params['limit'] == 20
        calls.append(params)
        return pages[len(calls) - 1]
    return NS(start=lambda: None, rpc=NS(request=request)), calls


def test_native_paging_maps_user_ids_and_groups_response_and_process_once():
    turn = {'id': 't', 'items': [{'id': 'u', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'question'}]},
        {'id': 'c', 'type': 'contextCompaction'}, {'id': 'tool', 'type': 'mcpToolCall'},
        {'id': 'a', 'type': 'agentMessage', 'text': 'answer'}]}
    c, calls = client([{'data': [turn], 'nextCursor': 'older'}, {'data': [{'id': 'older', 'items': []}]}])
    signature, records, _ = native_history_signature(c, 's', records=[{'turn_id': 't', 'item_id': '__response__'}])
    assert len(signature) == 1 and records == [{'turn_id': 't', 'item_id': '__response__'}]
    assert calls[1]['cursor'] == 'older'
    c, _ = client([{'data': [{'id': 't', 'items': [dict(turn['items'][0], id='new-generated-id')]}]}])
    assert native_history_signature(c, 's')[0] == signature


@pytest.mark.parametrize('pages,records', [
    ([{'data': [], 'nextCursor': 'same'}, {'data': [], 'nextCursor': 'same'}], []),
    ([{'data': []}], [{'turn_id': 'gone', 'item_id': 'u'}]),
    ([{'data': [{'id': 'duplicate'}, {'id': 'duplicate'}]}], [])])
def test_native_paging_fails_closed_for_changed_or_duplicate_history(pages, records):
    c, _ = client(pages)
    with pytest.raises(ValueError): native_history_signature(c, 's', records=records)


def test_projection_order_is_chronological_after_native_descending_pages():
    c, _ = client([{'data': [{'id': 'new'}], 'nextCursor': 'older'}, {'data': [{'id': 'old'}]}])
    assert [t['id'] for t in native_history_signature(c, 's', retain=True)[2]] == ['old', 'new']
