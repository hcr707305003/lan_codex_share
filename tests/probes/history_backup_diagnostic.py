"""Read a backup into an isolated native home; never edit the original session."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.probes.history_rebuild_native import native
from lan_codex_share.history_native import native_history_signature
from lan_codex_share.history_rebuild import apply_rebuilt_history, digest_file
from lan_codex_share.history_edit import native_writer_guard

def run(backup, target):
    base = Path(tempfile.mkdtemp(prefix='history-backup-diagnostic-'))
    home = base / 'home'; home.mkdir()
    (home / 'config.toml').write_text('model_provider="probe"\n[model_providers.probe]\nname="Offline diagnostic"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\n', encoding='utf-8')
    with backup.open('rb') as stream:
        meta = json.loads(next(stream)); sid = meta['payload']['id']
    provider = meta['payload'].get('model_provider', 'probe')
    (home / 'config.toml').write_text(f'model_provider={json.dumps(provider)}\n[model_providers.{json.dumps(provider)}]\nname="Offline diagnostic"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\n', encoding='utf-8')
    path = home / 'sessions' / '2026' / '11' / '01' / f'rollout-2026-11-01T00-00-00-{sid}.jsonl'
    path.parent.mkdir(parents=True); shutil.copyfile(backup, path)
    with native(home) as rpc:
        # Populate only this isolated home index, then release the writer.
        rpc.request('thread/resume', {'threadId': sid, 'path': str(path), 'approvalPolicy':'never', 'sandbox':'read-only'}, timeout=120)
    with native(home) as rpc:
        client = NS(start=lambda: None, rpc=rpc)
        _, _, before = native_history_signature(client, sid, retain=True)
        t = next(t for t in before if t['id'] == target)
        user = next(i for i in t['items'] if i['type'] == 'userMessage')
        selection = [{'turn_id': target, 'item_id': '__response__'}, {'turn_id': target, 'item_id': user['id']}]
        expected, records, _ = native_history_signature(client, sid, records=selection)
        def verify(*_):
            signature, _, checked = native_history_signature(client, sid, retain=True)
            if signature != expected:
                changed = [key for key in expected.keys() | signature.keys() if expected.get(key) != signature.get(key)]
                print(json.dumps({'directory':str(base), 'changed':changed}), flush=True)
            assert signature == expected, 'Native semantic mismatch after index sync'
        apply_rebuilt_history(path, home, sid, records=records, expected_revision=digest_file(path),
            writer_guard=native_writer_guard(home,sid),verify=verify)
        actual, _, after = native_history_signature(client, sid, retain=True)
        changed = [tid for tid in expected.keys() | actual.keys() if expected.get(tid) != actual.get(tid)]
        print(json.dumps({'directory':str(base), 'turns':len(before), 'changed':changed, 'selected':target}))
        old = {t['id']:t for t in before}; new = {t['id']:t for t in after}
        differences=[]
        for tid in changed:
            a=[{k:v for k,v in i.items() if k!='id'} for i in old.get(tid,{}).get('items',[]) if i.get('type')!='contextCompaction']
            b=[{k:v for k,v in i.items() if k!='id'} for i in new.get(tid,{}).get('items',[]) if i.get('type')!='contextCompaction']
            if tid==target: a=[]
            def compare(x,y,p=''):
                if type(x)!=type(y): return [p+':type']
                if isinstance(x,dict): return sum((compare(x.get(k),y.get(k),p+'.'+k) for k in x.keys()|y.keys()),[])
                if isinstance(x,list):
                    if len(x)!=len(y): return [p+f':length {len(x)} -> {len(y)}']
                    return sum((compare(v,y[n],p+f'[{n}]') for n,v in enumerate(x)),[])
                return [p] if x!=y else []
            differences.append({'turn':tid,'paths':compare(a,b)[:30], 'types_before':[i['type'] for i in a], 'types_after':[i['type'] for i in b]})
        print(json.dumps(differences))
    with native(home) as rpc:
        resumed = rpc.request('thread/resume', {'threadId':sid,'path':str(path), 'approvalPolicy':'never','sandbox':'read-only'},timeout=120)
        assert resumed['thread']['id'] == sid
    print(json.dumps({'native_resume_passed':True,'original_untouched':True}),flush=True)

if __name__=='__main__': run(Path(sys.argv[1]), sys.argv[2])
