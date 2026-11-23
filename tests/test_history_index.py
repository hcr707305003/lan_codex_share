import json
import sqlite3
import pytest
from lan_codex_share.history_index import HistoryIndexEdit
from lan_codex_share.history_rebuild import apply_rebuilt_history, digest_file
from tests.test_history_edit import message_history


def fixture(home):
    db = sqlite3.connect(home / 'thread_history_1.sqlite')
    db.executescript('CREATE TABLE thread_turns(thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, rollout_byte_offset INTEGER, rollout_end_ordinal INTEGER, rollout_end_byte_offset INTEGER, first_user_item_id TEXT, final_agent_item_id TEXT);\nCREATE TABLE thread_items(thread_id TEXT,turn_id TEXT,item_id TEXT,rollout_ordinal INTEGER,updated_at_ordinal INTEGER,item_json TEXT);\nCREATE TABLE thread_history_projection_state(thread_id TEXT,next_rollout_byte_offset INTEGER,next_rollout_ordinal INTEGER);')
    rows = message_history()
    for ordinal, row in enumerate(rows): row['ordinal'] = ordinal
    path = home / 'sessions' / 'rollout.jsonl'; path.parent.mkdir()
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    for sid in ['original', 'other']:
        db.execute('INSERT INTO thread_turns VALUES(?,?,?,?,?,?,?,?)',(sid,'turn',1,100,6,999,'u','a'))
        db.executemany('INSERT INTO thread_items VALUES(?,?,?,?,?,?)',[(sid,'turn','u',3,3,'question'),(sid,'turn','a',5,5,'answer')])
        db.execute('INSERT INTO thread_history_projection_state VALUES(?,?,?)',(sid,999,7))
    db.commit(); db.close()
    return path


def snapshot(home):
    with sqlite3.connect(home / 'thread_history_1.sqlite') as db:
        return [db.execute('SELECT * FROM '+t+' ORDER BY thread_id').fetchall() for t in HistoryIndexEdit.tables if t != 'thread_realtime_items']


@pytest.mark.parametrize('failed',[False,True])
def test_native_index_and_rollout_are_changed_or_restored_together(tmp_path,failed):
    path=fixture(tmp_path); before=path.read_bytes(); old=snapshot(tmp_path)
    def verify(*_):
        with sqlite3.connect(tmp_path/'thread_history_1.sqlite') as db:
            assert db.execute('SELECT item_id FROM thread_items WHERE thread_id=?',('original',)).fetchall()==[('u',)]
            assert db.execute('SELECT count(*) FROM thread_items WHERE thread_id=?',('other',)).fetchone()==(2,)
            offset,ordinal=db.execute('SELECT next_rollout_byte_offset,next_rollout_ordinal FROM thread_history_projection_state WHERE thread_id=?',('original',)).fetchone()
            assert offset==path.stat().st_size
            last=json.loads(path.read_text(encoding='utf-8').splitlines()[-1]); assert last['ordinal']+1==ordinal
        if failed: raise ValueError('native verification failed')
    kwargs=dict(records=[{'turn_id':'turn','item_id':'__response__'}],expected_revision=digest_file(path),verify=verify)
    if failed:
        with pytest.raises(ValueError,match='verification'):apply_rebuilt_history(path,tmp_path,'original',**kwargs)
        assert path.read_bytes()==before and snapshot(tmp_path)==old
    else:
        result=apply_rebuilt_history(path,tmp_path,'original',**kwargs)
        assert result['deleted_messages']==1
        assert list((tmp_path/'history-edit-backups').glob('*.history.sqlite'))
