const {test} = require('node:test');
const assert = require('node:assert/strict');
const {StreamSnapshot} = require('../../lan_codex_share/web/realtime.js');
const initial = () => ({sequence:1, snapshot:{version:1, history:{epoch:'a'},thread:{turns:[
  {id:'t',items:[{id:'a',type:'agentMessage',text:'hello'}]}, {id:'unchanged',items:[]},
]}}});
const delta = () => ({base:1,sequence:2,fields:{version:2},removed:[],thread_fields:{},thread_removed:[],order:['t','unchanged'],
  turns:[{id:'t',fields:{history_revision:1},removed:[],order:['a'],items:[{id:'a',append:' world'}]}]});

test('append reconstructs snapshot and preserves unchanged references', () => {
  const state = new StreamSnapshot(); const first = state.apply('snapshot', initial());
  const next = state.apply('delta', delta());
  assert.equal(next.thread.turns[0].items[0].text,'hello world');
  assert.equal(first.thread.turns[0].items[0].text,'hello');
  assert.equal(next.thread.turns[1], first.thread.turns[1]);
});
test('new baseline after reconnect does not double append', () => {
  const state = new StreamSnapshot();state.apply('snapshot',initial());state.apply('delta',delta());
  state.apply('snapshot',initial());
  assert.equal(state.apply('delta',delta()).thread.turns[0].items[0].text,'hello world');
});
test('missing or duplicated sequence rejected without modifying baseline', () => {
  const state = new StreamSnapshot(); const old = state.apply('snapshot', initial());
  assert.throws(()=>state.apply('delta',{...delta(),base:0}));
  assert.equal(state.snapshot,old);
  state.apply('delta',delta()); assert.throws(()=>state.apply('delta',delta()));
});
test('turn replacement and deleted fields follow order exactly', () => {
  const state = new StreamSnapshot();state.apply('snapshot',initial());
  const patch = delta(); patch.removed=['history'];patch.order=['new'];patch.turns=[{id:'new',replace:{id:'new',items:[]}}];
  const value=state.apply('delta',patch);
  assert.deepEqual(value.thread.turns,[{id:'new',items:[]}]); assert.equal(value.history,undefined);
});
