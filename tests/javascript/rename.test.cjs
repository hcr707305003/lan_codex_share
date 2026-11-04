const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');
const block = source.slice(source.indexOf('// Capture the session at dialog open:'), source.indexOf("resyncButton.addEventListener('click'"));
function setup(mutate) {
  const nodes = {};
  const node = id => nodes[id] ||= {value:'', textContent:'', disabled:false, handlers:{},
    addEventListener(type, callback){this.handlers[type]=callback;},
    showModal(){this.open=true;}, close(){this.open=false;}, focus(){}, select(){}};
  const context = vm.createContext({document:{getElementById:node}, selectedSessionId:'a',
    latestSnapshot:{thread:{name:'Old'}}, threadTitle:{textContent:'Old'}, closeMenu(){},
    mutateForSession:mutate, setNotice(){}, refresh:async()=>{}});
  vm.runInContext(block, context);
  node('rename-session').handlers.click();
  return {node, context, submit:()=>node('rename-form').handlers.submit({preventDefault(){}})};
}
test('rename captures session and suppresses duplicate submissions', async()=>{
  let resolve, calls=[];
  const ui=setup((...args)=>{calls.push(args);return new Promise(r=>resolve=r);});
  ui.context.selectedSessionId='b';
  ui.node('rename-name').value=' New ';
  const saving=ui.submit();
  await ui.submit();
  assert.equal(calls.length,1);
  assert.equal(calls[0][1],'a');
  assert.equal(calls[0][2].name,'New');
  assert.equal(ui.node('rename-save').disabled,true);
  resolve(); await saving;
  assert.equal(ui.node('rename-dialog').open,false);
});
test('failed rename keeps draft and allows retry', async()=>{
  const ui=setup(async()=>{throw Error('失败');});
  ui.node('rename-name').value='Draft';
  await ui.submit();
  assert.equal(ui.node('rename-dialog').open,true);
  assert.equal(ui.node('rename-name').value,'Draft');
  assert.equal(ui.node('rename-error').textContent,'失败');
  assert.equal(ui.node('rename-save').disabled,false);
});
