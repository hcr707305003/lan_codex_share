import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import pytest
from lan_codex_share.session_migration import SessionMigration, unpack


def fixture(tmp_path):
    sid=str(uuid4()); home=tmp_path/'source'; path=home/'sessions'/'test.jsonl';path.parent.mkdir(parents=True)
    rows=[{'type':'session_meta','payload':{'id':sid,'timestamp':'2026-11-17T08:00:00Z','cwd':'C:/old','project_id':'old'}}, {'type':'event_msg','payload':{'type':'user_message','message':'original C:/old text'}}, {'type':'turn_context','payload':{'cwd':'C:/old'}}]
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    client=Mock();client.read_thread_metadata.return_value={'id':sid,'name':'迁移测试','cwd':'C:/old','path':str(path)}
    tasks=SimpleNamespace(client=client,shared_ids=lambda:[sid],hub=None,config_store=None)
    package = SessionMigration(tasks,home).export(sid)
    data = package.read_bytes(); package.unlink()
    return sid, data


def test_native_migration_registers_and_preserves_history(tmp_path):
    sid,data=fixture(tmp_path)
    project=tmp_path/'project'; project.mkdir()
    client=Mock(sandbox_mode='read-only');client.list_threads.return_value=[]
    client.rpc.request.return_value={'thread':{'id':sid}}
    client.read_thread_metadata.return_value={'id':sid,'cwd':str(project)}
    tasks=SimpleNamespace(client=client,projects=lambda:{'items':[{'cwd':str(project)}]},config_store=None,_persist_entry=Mock(return_value={'session_id':sid}))
    migration=SessionMigration(tasks,tmp_path/'target')
    assert migration.restore(data,str(project))['session_id']==sid
    path=next((tmp_path/'target').rglob('*.jsonl')); rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert rows[0]['payload']['cwd']==str(project)
    assert 'project_id' not in rows[0]['payload']
    assert rows[1]['payload']['message']=='original C:/old text'
    assert rows[2]['payload']['cwd']==str(project)
    client.rename_thread.assert_called_once_with(sid,'迁移测试')
    with pytest.raises(ValueError,match='不会覆盖'): migration.restore(data,str(project))


def test_bad_migration_and_unapproved_project(tmp_path):
    _, data=fixture(tmp_path)
    for bad in (b'notzip',data[:40]):
        with pytest.raises(ValueError): unpack(bad)
    tasks=SimpleNamespace(projects=lambda:{'items':[]})
    with pytest.raises(ValueError,match='目标电脑'):SessionMigration(tasks,tmp_path/'target').restore(data,'C:/other')
    assert not (tmp_path/'target').exists()


def test_failed_native_registration_is_not_success_or_deleted(tmp_path):
    sid,data=fixture(tmp_path);project=tmp_path/'project';project.mkdir()
    client=Mock(sandbox_mode='read-only');client.list_threads.return_value=[];client.rpc.request.side_effect=TimeoutError()
    tasks=SimpleNamespace(client=client,projects=lambda:{'items':[{'cwd':str(project)}]},config_store=None,_persist_entry=Mock())
    with pytest.raises(ValueError,match='登记或共享未完成'):SessionMigration(tasks,tmp_path/'target').restore(data,str(project))
    tasks._persist_entry.assert_not_called()
    assert len(list((tmp_path/'target').rglob('*.jsonl')))==1


def test_rejects_tampered_and_traversal_packages(tmp_path):
    from io import BytesIO
    import zipfile
    _, data = fixture(tmp_path)
    for extra in (True, False):
        out = BytesIO()
        with zipfile.ZipFile(BytesIO(data)) as original, zipfile.ZipFile(out, 'w') as edited:
            for name in original.namelist():
                value = original.read(name)
                if name == 'rollout.jsonl' and not extra:
                    value += b'\n'
                edited.writestr(name, value)
            if extra:
                edited.writestr('../outside', b'bad')
        with pytest.raises(ValueError):
            unpack(out.getvalue())


def test_export_shared_history_over_old_32_mib_limit(tmp_path):
    sid = str(uuid4())
    home = tmp_path/'large-source'; path = home/'sessions'/'large.jsonl'; path.parent.mkdir(parents=True)
    with path.open('w', encoding='utf-8') as f:
        f.write(json.dumps({'type':'session_meta','payload':{'id':sid,'timestamp':'2026-11-17T08:00:00Z','cwd':str(tmp_path)}})+'\n')
        line = json.dumps({'type':'event_msg','payload':{'type':'user_message','message':'x'*4096}})+'\n'
        for _ in range(8500): f.write(line)
    assert path.stat().st_size > 32*1024*1024
    client = Mock();client.read_thread_metadata.return_value={'id':sid,'name':'大历史','cwd':str(tmp_path),'path':str(path)}
    tasks = SimpleNamespace(client=client, shared_ids=lambda:[sid], hub=None)
    migration = SessionMigration(tasks,home)
    package = migration.export(sid)
    try:
        manifest, rows = unpack(package)
        assert manifest['id'] == sid
        assert sum(1 for _ in rows) == 8501
    finally:
        package.unlink()


def test_export_rejects_unshared_before_reading_native_history(tmp_path):
    client = Mock()
    tasks = SimpleNamespace(client=client, shared_ids=lambda:[], hub=None)
    with pytest.raises(ValueError, match='只能导出共享任务'):
        SessionMigration(tasks,tmp_path).export(str(uuid4()))
    client.read_thread_metadata.assert_not_called()


def test_prepared_download_expiry_and_shared_membership(tmp_path, monkeypatch):
    sid=str(uuid4());shared=[sid];path=tmp_path/'package.zip';path.write_bytes(b'zip')
    migration=SessionMigration(SimpleNamespace(shared_ids=lambda:shared),tmp_path)
    monkeypatch.setattr(migration,'export',lambda _:path)
    result=migration.prepare_download(sid)
    token=result['url'].rsplit('/',1)[-1]
    assert migration.download(token)[0]==path
    shared.clear()
    with pytest.raises(ValueError,match='移出共享'): migration.download(token)
    shared.append(sid)
    migration._expire_download(token)
    assert not path.exists()
    with pytest.raises(ValueError,match='过期'): migration.download(token)


def test_import_copy_on_same_machine_preserves_original(tmp_path):
    sid, data = fixture(tmp_path)
    home = tmp_path/'source'; original = home/'sessions'/'test.jsonl'
    before = original.read_bytes()
    project = tmp_path/'project'; project.mkdir()
    client = Mock(sandbox_mode='read-only'); client.list_threads.return_value=[{'id':sid}]
    client.rpc.request.side_effect=lambda method, params, **kw: {'thread':{'id':params['threadId']}}
    client.read_thread_metadata.side_effect=lambda new_id: {'id':new_id,'cwd':str(project)}
    tasks=SimpleNamespace(client=client,projects=lambda:{'items':[{'cwd':str(project)}]},config_store=None,_persist_entry=lambda entry,confirmed:{'session_id':entry['id']})
    migration=SessionMigration(tasks,home)
    with pytest.raises(ValueError,match='不会覆盖'): migration.restore(data,str(project))
    first=migration.restore(data,str(project),as_copy=True)['session_id']
    second=migration.restore(data,str(project),as_copy=True)['session_id']
    assert len({sid,first,second})==3
    assert original.read_bytes()==before
    new_path=next((home/'sessions').rglob('*'+first+'*.jsonl'))
    rows=[json.loads(line) for line in new_path.read_text(encoding='utf-8').splitlines()]
    assert rows[0]['payload']['id']==first
    assert rows[1]['payload']['message']=='original C:/old text'
    client.rename_thread.assert_any_call(first,'迁移测试（副本）')
