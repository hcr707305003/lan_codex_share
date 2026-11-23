const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../lan_codex_share/web/app.js'),'utf8');
function setup(fetchHistoryJson, mutateForSession=async()=>({id:'job'})) {
 const nodes=new Map();
 const get=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,disabled:false,textContent:'',handlers:{},addEventListener(k,fn){this.handlers[k]=fn;}});return nodes.get(id);};
 const c=vm.createContext({document:{getElementById:get,querySelectorAll:()=>[]},selectedSessionId:'original',
  fetchHistoryJson,mutateForSession,URLSearchParams,closeSidebar(){},setTimeout});
 vm.runInContext(source.slice(source.indexOf('let inlineHistory =')),c);
 return {c,get};
}
test('inline deletion submits selected native messages directly and preserves target session',async()=>{
 let payload;
 const {c,get}=setup(async url=>url.includes('delete-status')?
  {state:'done',message:'done',result:{deleted_messages:1}}:{revision:'revision',blocked_reason:null},
  async(path,sid,body)=>{payload={path,sid,body};return{id:'job'};});
 await c.enterInlineHistorySelection();
 vm.runInContext("inlineHistory.selected.add(JSON.stringify(['turn','middle'])); updateInlineHistoryControls();",c);
 assert.equal(get('inline-history-delete').disabled,false);
 await get('inline-history-delete').handlers.click();
 assert.equal(payload.sid,'original');assert.equal(payload.path,'/api/history/delete-messages');
 assert.equal(payload.body.records[0].turn_id,'turn');assert.equal(payload.body.records[0].item_id,'middle');assert.equal(payload.body.confirmed,true);
 assert.match(get('inline-history-status').textContent,/已删除 1 条/);
 assert.equal(get('inline-history-delete').disabled,true);
});
test('closing inline mode prevents late preflight from enabling deletion',async()=>{
 let finish;
 const {c,get}=setup(()=>new Promise(resolve=>{finish=resolve;}));
 const pending=c.enterInlineHistorySelection();c.exitInlineHistorySelection();
 finish({revision:'old',blocked_reason:null});await pending;
 assert.equal(get('inline-history-bar').hidden,true);
 assert.equal(vm.runInContext('inlineHistory.active',c),false);
});

test('successful native reacquire shows connected completion instead of released', async()=>{
 const {c,get}=setup(async url=>url.includes('delete-status')?
  {state:'done',result:{deleted_messages:2,connection:'connected',context_reset:true}}:
  {revision:'revision',blocked_reason:null});
 await c.enterInlineHistorySelection();
 vm.runInContext("inlineHistory.selected.add(JSON.stringify(['t','__response__'])); updateInlineHistoryControls();",c);
 await get('inline-history-delete').handlers.click();
 assert.match(get('inline-history-status').textContent,/已重新接管原会话/);
 assert.doesNotMatch(get('inline-history-status').textContent,/会话已释放|删除未完成/);
});

test('reacquire failure retains successful deletion and explains writer conflict', async()=>{
 const {c,get}=setup(async url=>url.includes('delete-status')?
  {state:'done',result:{deleted_messages:2,connection:'released',reconnect_error:'active writer'}}:
  {revision:'revision',blocked_reason:null});
 await c.enterInlineHistorySelection();
 vm.runInContext("inlineHistory.selected.add(JSON.stringify(['t','__response__'])); updateInlineHistoryControls();",c);
 await get('inline-history-delete').handlers.click();
 assert.match(get('inline-history-status').textContent,/删除成功，但重新接管失败：active writer/);
 assert.doesNotMatch(get('inline-history-status').textContent,/删除未完成/);
});

test('compacted sessions show the recent-context reset notice and allow deletion', async()=>{
 const {c,get}=setup(async url=>url.includes('delete-status')?
  {state:'done',message:'done',result:{deleted_messages:1,context_reset:true}}:
  {revision:'revision',blocked_reason:null,context_notice:'较早记录仍可查看；删除时重建近期文字上下文'});
 await c.enterInlineHistorySelection();
 assert.match(get('inline-history-status').textContent,/近期文字上下文/);
 vm.runInContext("inlineHistory.selected.add(JSON.stringify(['t','__response__'])); updateInlineHistoryControls();",c);
 assert.equal(get('inline-history-delete').disabled,false);
 await get('inline-history-delete').handlers.click();
 assert.match(get('inline-history-status').textContent,/旧压缩摘要已清除/);
});

test('blocked native deletion still permits visible selection without enabling submission',async()=>{
 const {c,get}=setup(async()=>({revision:'revision',blocked_reason:'压缩历史暂不支持删除'}));
 await c.enterInlineHistorySelection();
 vm.runInContext("inlineHistory.selected.add('turn'); updateInlineHistoryControls();",c);
 assert.equal(get('inline-history-count').textContent,'已选 1 条');
 assert.equal(get('inline-history-clear').disabled,false);
 assert.equal(get('inline-history-delete').disabled,true);
 assert.match(get('inline-history-status').textContent,/压缩历史/);
 get('inline-history-clear').handlers.click();
 assert.equal(get('inline-history-count').textContent,'已选 0 条');
});

test('each user/assistant record gets a side checkbox without linked turn selection', async()=>{
 const {c}=setup(async()=>({revision:'revision',blocked_reason:null}));
 c.window={getSelection:()=>({isCollapsed:true,toString:()=>''})};
 const node=()=>({children:[],handlers:{},classList:{toggle(){},contains(){return false;}},setAttribute(){},
  append(n){this.children.push(n);},prepend(n){this.children.unshift(n);},
  querySelector(){return this.children[0];},addEventListener(k,fn){this.handlers[k]=fn;}});
 const messages=[node(),node()];messages.forEach((m,i)=>m.dataset={messageId:'message-'+i});
 const section={dataset:{turnId:'native-turn'},querySelectorAll:()=>messages};
 c.document.querySelectorAll=()=>[section];c.document.createElement=node;c.el=node;
 await c.enterInlineHistorySelection();
 for(const message of messages){
  assert.ok(message.historyCheckbox);assert.equal(message.historyCheckbox.children.length,1);
  assert.equal(message.historyCheckbox.hidden,false);
  assert.equal(message.historyCheckbox.querySelector().disabled,false);
 }
 const first=messages[0].historyCheckbox.querySelector();first.checked=true;first.handlers.change();
 assert.equal(messages[1].historyCheckbox.querySelector().checked,false);
 assert.equal(vm.runInContext('inlineHistory.selected.size',c),1);
 // Clicking another message selects it independently.
 const plain={target:{closest:()=>null}};
 messages[1].handlers.click(plain);
 assert.equal(first.checked,true);
 assert.equal(messages[1].historyCheckbox.querySelector().checked,true);
 assert.equal(vm.runInContext('inlineHistory.selected.size',c),2);
 messages[0].handlers.click(plain);
 assert.equal(first.checked,false);
 messages[0].handlers.click(plain);
 assert.equal(first.checked,true);
 // Links/buttons and a text selection preserve their normal interaction.
 messages[0].handlers.click({target:{closest:()=>({})}});
 assert.equal(first.checked,true);
 c.window.getSelection=()=>({isCollapsed:false,toString:()=> 'selected text'});
 messages[0].handlers.click(plain);
 assert.equal(first.checked,true);
 c.exitInlineHistorySelection();
 assert.ok(messages.every(m=>m.historyCheckbox.hidden));
});

test('process and final reply share one visible checkbox and one deletion record', async()=>{
 let submitted;
 const {c,get}=setup(async url=>url.includes('delete-status')?
  {state:'done',message:'done',result:{deleted_messages:1}}:{revision:'revision'},
  async(path,sid,body)=>{submitted=body;return{id:'job'};});
 c.window={getSelection:()=>null};
 const node=(classes=[])=>({children:[],handlers:{},dataset:{},classList:{toggle(){},contains(k){return classes.includes(k);}},
  setAttribute(){},append(n){this.children.push(n);},prepend(n){this.children.unshift(n);},
  querySelector(){return this.children[0];},addEventListener(k,fn){this.handlers[k]=fn;}});
 const user=node(['user']);user.dataset.messageId='user';
 const process=node(['activity-group']);const summary=node();process.children.push(summary);
 const answer=node(['assistant']);answer.dataset.messageId='reply';
 const records=[user,process,answer];
 const section={dataset:{turnId:'turn'},querySelectorAll:()=>records};
 c.document.querySelectorAll=()=>[section];c.document.createElement=()=>node();c.el=()=>node();
 await c.enterInlineHistorySelection();
 assert.equal(process.historyCheckbox.hidden,false);
 assert.equal(answer.historyCheckbox.hidden,true);
 assert.equal(user.historyCheckbox.hidden,false);
 answer.handlers.click({target:{closest:()=>null}});
 assert.equal(process.historyCheckbox.querySelector().checked,true);
 assert.equal(user.historyCheckbox.querySelector().checked,false);
 assert.equal(get('inline-history-count').textContent,'已选 1 条');
 const checkbox=process.historyCheckbox.querySelector();checkbox.checked=false;checkbox.handlers.change();
 assert.equal(answer.historyCheckbox.querySelector().checked,false);
 get('inline-history-visible').handlers.click();
 assert.equal(get('inline-history-count').textContent,'已选 2 条');
 get('inline-history-clear').handlers.click();
 answer.handlers.click({target:{closest:()=>null}});
 await get('inline-history-delete').handlers.click();
 assert.equal(submitted.records.length,1);
 assert.equal(submitted.records[0].item_id,'__response__');
});
