"""Paged native projection verification without retaining every tool response."""
import hashlib
import json


def native_history_signature(client, sid, *, records=(), deleted_turns=(), retain=False):
    client.start()
    requested = {(r['turn_id'], r['item_id']) for r in records}
    selected_turns = set(deleted_turns)
    found, native_records, pages, seen, turns = set(), [], set(), set(), []
    signatures = {}
    cursor = None
    while True:
        params = {'threadId': sid, 'itemsView': 'full', 'limit': 20}
        if cursor: params['cursor'] = cursor
        page = client.rpc.request('thread/turns/list', params, timeout=120)
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise ValueError('Codex 原生历史分页格式无效')
        for turn in page['data']:
            tid = turn.get('id')
            if not tid or tid in seen: raise ValueError('Codex 原生历史分页重复或缺少轮次 ID')
            seen.add(tid)
            if retain: turns.append(turn)
            if tid in selected_turns: continue
            keep = []
            for item in turn.get('items', []):
                key = (tid, item.get('id'))
                response = (tid, '__response__') in requested and item.get('type') != 'userMessage'
                process = (tid, '__process__') in requested and not (item.get('type') == 'userMessage' or
                    (item.get('type') == 'agentMessage' and item.get('phase') != 'commentary'))
                if response: found.add((tid, '__response__'))
                if process: found.add((tid, '__process__'))
                if key in requested:
                    found.add(key); native_records.append({'turn_id': tid, 'item_id': item['id'], '_native': item})
                if item.get('type') == 'contextCompaction' or response or process or key in requested: continue
                keep.append({k: v for k, v in item.items() if k != 'id'})
            if keep:
                signatures[tid] = hashlib.sha256(json.dumps(keep, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        cursor = page.get('nextCursor')
        if not cursor: break
        if not isinstance(cursor, str) or cursor in pages: raise ValueError('Codex 原生历史分页游标无效')
        pages.add(cursor)
    if not selected_turns.issubset(seen) or found != requested:
        raise ValueError('所选原生记录已变化或不存在，请重新加载')
    native_records.extend({'turn_id': tid, 'item_id': iid} for tid, iid in sorted(requested) if iid in {'__response__', '__process__'})
    if retain: turns.reverse()  # Native paged turns are newest first.
    return signatures, native_records, turns
