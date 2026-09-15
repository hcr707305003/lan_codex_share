from typing import Any


def fields(new: dict, old: dict, excluded=()) -> tuple[dict, list]:
    return (
        {key: value for key, value in new.items() if key not in excluded and (key not in old or value != old[key])},
        [key for key in old if key not in new and key not in excluded],
    )


def turn_delta(new: dict, old: dict | None) -> dict:
    if old is None:
        return {'id': new['id'], 'replace': new}
    changed, removed = fields(new, old, ('items',))
    previous = {item['id']: item for item in old.get('items', [])}
    items = []
    for item in new.get('items', []):
        prior = previous.get(item['id'])
        if item == prior:
            continue
        if (prior and item.get('type') == 'agentMessage'
                and isinstance(item.get('text'), str) and isinstance(prior.get('text'), str)
                and item['text'].startswith(prior['text'])
                and fields(item, prior, ('text',)) == ({}, [])):
            items.append({'id': item['id'], 'append': item['text'][len(prior['text']):]})
        else:
            items.append({'id': item['id'], 'replace': item})
    return {'id': new['id'], 'fields': changed, 'removed': removed, 'items': items,
            'order': [item['id'] for item in new.get('items', [])]}


class SnapshotDelta:
    """Per-connection, bounded recent-page baseline; never replay raw reasoning."""

    def __init__(self):
        self.previous: dict[str, Any] | None = None
        self.sequence = 0

    def next(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        old = self.previous
        if snapshot == old:
            return None
        self.sequence += 1
        reset = old is None or snapshot.get('thread_id') != old.get('thread_id') or (
            snapshot.get('history', {}).get('epoch') != old.get('history', {}).get('epoch')
        )
        if reset:
            result = {'event': 'snapshot', 'data': {'sequence': self.sequence, 'snapshot': snapshot}}
        else:
            changed, removed = fields(snapshot, old, ('thread',))
            thread = snapshot.get('thread', {})
            previous_thread = old.get('thread', {})
            thread_fields, thread_removed = fields(thread, previous_thread, ('turns',))
            previous = {turn['id']: turn for turn in previous_thread.get('turns', [])}
            result = {'event': 'delta', 'data': {
                'base': self.sequence - 1, 'sequence': self.sequence,
                'fields': changed, 'removed': removed,
                'thread_fields': thread_fields, 'thread_removed': thread_removed,
                'order': [turn['id'] for turn in thread.get('turns', [])],
                'turns': [turn_delta(turn, previous.get(turn['id'])) for turn in thread.get('turns', [])
                          if turn != previous.get(turn['id'])],
            }}
        # Callers supply fresh snapshots; retain only the last 20-turn page.
        self.previous = snapshot
        return result
