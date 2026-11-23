"""Synchronize the paginated native history projection with a rewritten rollout.

Only the selected thread's derived rows are touched. The caller must hold the
native writer lock and restore the rollout if verification fails.
"""
import json
from pathlib import Path
import sqlite3


class HistoryIndexEdit:
    tables = ('thread_turns', 'thread_items', 'thread_realtime_items', 'thread_history_projection_state')

    def __init__(self, home, sid, backup):
        self.path = Path(home) / 'thread_history_1.sqlite'
        self.sid = sid
        self.backup = Path(str(backup) + '.history.sqlite')
        self.active = False

    def capture(self):
        if not self.path.exists(): return
        with sqlite3.connect(self.path) as source, sqlite3.connect(self.backup) as target:
            source.execute('BEGIN')
            for table in self.tables:
                schema = source.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone()
                if schema is None:
                    if table == 'thread_realtime_items': continue
                    raise ValueError('Codex 历史索引结构不支持，历史未修改')
                target.execute(schema[0])
                cursor = source.execute(f'SELECT * FROM {table} WHERE thread_id=?', (self.sid,))
                insert = f'INSERT INTO {table} VALUES ({",".join("?" for _ in cursor.description)})'
                while rows := cursor.fetchmany(100): target.executemany(insert, rows)
        self.active = True

    def restore(self):
        if not self.active: return
        with sqlite3.connect(self.path, timeout=30) as target, sqlite3.connect(self.backup) as source:
            for (table,) in source.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if table not in self.tables: raise ValueError('历史索引备份结构无效')
                target.execute(f'DELETE FROM {table} WHERE thread_id=?', (self.sid,))
                cursor = source.execute(f'SELECT * FROM {table}')
                insert = f'INSERT INTO {table} VALUES ({",".join("?" for _ in cursor.description)})'
                while rows := cursor.fetchmany(100): target.executemany(insert, rows)

    def sync(self, rollout):
        if not self.active: return
        # Ordinals remain stable (gaps are valid); offsets change after rewriting.
        offsets, turns, items = {}, {}, {}
        active = None; end = 0; last = -1
        with Path(rollout).open('rb') as stream:
            while raw := stream.readline():
                start = end; end += len(raw)
                if not raw.strip(): continue
                row = json.loads(raw); p = row.get('payload', {}); ordinal = row.get('ordinal')
                if not isinstance(ordinal, int):
                    # Legacy rollouts use the native legacy reader, not this index.
                    if last == -1: return
                    raise ValueError('分页历史记录缺少 ordinal，已取消删除')
                if ordinal <= last: raise ValueError('分页历史 ordinal 重复或倒序')
                last = ordinal; offsets[ordinal] = (start, end)
                if row['type'] == 'event_msg' and p.get('type') == 'task_started':
                    active = p['turn_id']; turns[active] = [ordinal, ordinal, None, None]
                if active:
                    turns[active][1] = ordinal
                    if row['type'] == 'event_msg' and p.get('type') == 'item_completed':
                        item = p.get('item', {}); iid = item.get('id')
                        if iid:
                            items[(active, iid)] = ordinal
                            if item.get('type') == 'UserMessage' and turns[active][2] is None: turns[active][2] = iid
                            if item.get('type') == 'AgentMessage' and item.get('phase') != 'commentary': turns[active][3] = iid
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('BEGIN IMMEDIATE')
            for tid, in db.execute('SELECT turn_id FROM thread_turns WHERE thread_id=?', (self.sid,)).fetchall():
                if tid not in turns:
                    db.execute('DELETE FROM thread_turns WHERE thread_id=? AND turn_id=?', (self.sid, tid)); continue
                first, final, user, agent = turns[tid]
                db.execute('UPDATE thread_turns SET rollout_ordinal=?, rollout_byte_offset=?, rollout_end_ordinal=?, rollout_end_byte_offset=?, first_user_item_id=?, final_agent_item_id=? WHERE thread_id=? AND turn_id=?',
                    (first, offsets[first][0], final, offsets[final][1], user, agent, self.sid, tid))
            for tid, iid, previous, in db.execute('SELECT turn_id,item_id,rollout_ordinal FROM thread_items WHERE thread_id=?', (self.sid,)).fetchall():
                ordinal = items.get((tid, iid), previous if tid in turns and previous in offsets else None)
                if ordinal is None: db.execute('DELETE FROM thread_items WHERE thread_id=? AND turn_id=? AND item_id=?', (self.sid, tid, iid))
                else: db.execute('UPDATE thread_items SET rollout_ordinal=?,updated_at_ordinal=? WHERE thread_id=? AND turn_id=? AND item_id=?', (ordinal, ordinal, self.sid, tid, iid))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='thread_realtime_items'").fetchone():
                for iid, ordinal in db.execute('SELECT item_id,rollout_ordinal FROM thread_realtime_items WHERE thread_id=?', (self.sid,)).fetchall():
                    if ordinal not in offsets: db.execute('DELETE FROM thread_realtime_items WHERE thread_id=? AND item_id=?', (self.sid, iid))
            db.execute('UPDATE thread_history_projection_state SET next_rollout_byte_offset=?,next_rollout_ordinal=? WHERE thread_id=?', (end, last + 1, self.sid))
