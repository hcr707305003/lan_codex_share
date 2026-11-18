const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../lan_codex_share/web/app.js'),'utf8');
test('multi-export captures checked shared IDs and continues after individual failure', async () => {
  let submit;
  const boxes = [{value:'one'}, {value:'two'}, {value:'three'}];
  const requests=[]; const downloads=[];
  const c=vm.createContext({exportSelect:{querySelectorAll:()=>boxes},exportBusy:false,exportSubmit:{},exportMore:{},exportStatus:{},exportDownloads:{append(){}},csrf:'token',
    document:{getElementById:()=>({addEventListener:(_,fn)=>{submit=fn;}}),createElement:()=>({click(){downloads.push(this.download);}})},
    fetch:async (_,options)=>{const id=JSON.parse(options.body).export_session_id;requests.push(id);return id==='two'?{ok:false,json:async()=>({error:'已移出共享'})}:{ok:true,json:async()=>({url:'/api/migration/download/'+id,name:'codex-session-'+id+'.zip'}),blob:()=>{throw new Error('must not buffer download');}};},
    URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:()=>0});
  const start=source.indexOf("document.getElementById('migration-export-form').addEventListener");
  vm.runInContext(source.slice(start,source.indexOf("document.getElementById('import-session').addEventListener",start)),c);
  await submit({preventDefault(){}});
  assert.deepEqual(requests,['one','two','three']);
  assert.deepEqual(downloads,['codex-session-one.zip','codex-session-three.zip']);
  assert.match(c.exportStatus.textContent,/2\/3/);
  assert.match(c.exportStatus.textContent,/已移出共享/);
  assert.equal(c.exportSubmit.disabled,false);
});
