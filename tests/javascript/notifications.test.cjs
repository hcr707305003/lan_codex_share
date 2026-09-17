const {test} = require('node:test');
const assert = require('node:assert/strict');
const {TaskCompletionTracker, TaskNotifications} = require('../../lan_codex_share/web/notifications.js');
const snap = (turns, id='session-a') => ({thread_id:id, thread:{id, name:'Example', turns}});
const turn = (id, status) => ({id, status});

test('baseline ignores old endings, then detects every terminal state exactly once', () => {
  for (const status of ['completed', 'failed', 'interrupted', 'cancelled', 'canceled']) {
    const tracker = new TaskCompletionTracker();
    assert.deepEqual(tracker.update(snap([turn('old', status), turn('new', 'inProgress')])), []);
    assert.equal(tracker.update(snap([turn('new', status)])).length, 1);
    assert.equal(tracker.update(snap([turn('new', status)])).length, 0);
  }
});
test('quick turns, reconnect baseline, unknown states and stale status', () => {
  const tracker = new TaskCompletionTracker();
  tracker.update(snap([]));
  assert.equal(tracker.update(snap([turn('quick', 'completed')])).length, 1);
  tracker.update(snap([turn('quick', 'inProgress')]));
  assert.equal(tracker.update(snap([turn('quick', 'completed')])).length, 0);
  tracker.update(snap([turn('next', 'inProgress')]));
  assert.equal(tracker.update({...snap([turn('next', 'inProgress')]), connection:'released', status:'idle'}).length, 0);
  assert.equal(tracker.update(snap([turn('next', 'unknown')])).length, 0);
  assert.equal(tracker.update(snap([turn('next', 'constructor')])).length, 0);
  assert.equal(tracker.update(snap([turn('next', 'failed')])).length, 1);
});
test('switch and reset establish a fresh baseline, independent viewers', () => {
  const a = new TaskCompletionTracker(), b = new TaskCompletionTracker();
  for (const tracker of [a,b]) tracker.update(snap([turn('t', 'inProgress')]));
  assert.equal(a.update(snap([turn('t', 'completed')])).length, 1);
  assert.equal(b.update(snap([turn('t', 'completed')])).length, 1);
  assert.equal(a.update(snap([turn('t', 'completed')], 'session-b')).length, 0);
  a.reset();
  assert.equal(a.update(snap([turn('t', 'completed')])).length, 0);
});
test('copies status, accepts empty baseline only with valid session and turns', () => {
  const tracker = new TaskCompletionTracker();
  tracker.update({});
  const value = snap([turn('t', 'inProgress')]);
  tracker.update(value);
  value.thread.turns[0].status='completed';
  assert.equal(tracker.update(value).length, 1);
});

class Node {
  constructor() { this.children=[]; this.hidden=false; this.events={}; this.attrs={}; this.textContent=''; }
  append(...nodes) { for(const node of nodes) { node.parent=this; this.children.push(node); } }
  replaceChildren(...nodes) { this.children=[]; this.append(...nodes); }
  setAttribute(key,value) { this.attrs[key]=value; }
  addEventListener(key,value) { this.events[key]=value; }
  remove() { this.parent.children=this.parent.children.filter(n=>n!==this); }
  focus() { throw new Error('notification must not steal focus'); }
}
test('cards disabled by default, safe text, manual dismissal, reset on switch', () => {
  global.document={createElement:()=>new Node()};
  const root=new Node(); const ui=new TaskNotifications(root);
  ui.update(snap([turn('t','inProgress')]));
  ui.update(snap([turn('t','completed')]));
  assert.equal(root.children.length,0);
  ui.setEnabled(true); ui.update(snap([]));
  ui.update({...snap([turn('a','completed'),turn('b','failed')]),thread:{name:'<img onerror=evil()>',turns:[turn('a','completed'),turn('b','failed')]}});
  assert.equal(root.children.length,2);
  assert.ok(JSON.stringify(root.children[0].children.map(n=>n.textContent)).includes('<img onerror=evil()>'));
  root.children[0].children.at(-1).events.click();
  assert.equal(root.children.length,1);
  ui.update(snap([turn('a','completed'),turn('b','failed')]));
  assert.equal(root.children.length,1);
  ui.update(snap([], 'b'));
  assert.equal(root.children.length,0);
  ui.setEnabled(false);
  assert.equal(root.hidden,true);
});
