const assert = require('node:assert/strict');
const {test} = require('node:test');
const {HistoryTimeline} = require('../../lan_codex_share/web/history.js');

class Element {
  constructor() { this.children = []; this.scrollTop = 0; this.clientHeight = 300; this.parent = null; this.events = {}; }
  get scrollHeight() { return this.children.length * 100; }
  get firstElementChild() { return this.children[0] || null; }
  get nextElementSibling() { return this.parent?.children[this.parent.children.indexOf(this) + 1] || null; }
  setAttribute() {}
  addEventListener(event, fn) { this.events[event] = fn; }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
  insertBefore(node, target) { node.remove(); const i = target ? this.children.indexOf(target) : this.children.length; this.children.splice(i, 0, node); node.parent = this; }
  append(...nodes) { nodes.forEach(node => this.insertBefore(node, null)); }
  replaceChildren(...nodes) { for (const node of [...this.children]) node.remove(); this.append(...nodes); }
  getBoundingClientRect() { const top = this.parent ? this.parent.children.indexOf(this) * 100 - this.parent.scrollTop : 0; return {top, bottom: top + (this.parent ? 100 : 300)}; }
}
global.document = {createElement: () => new Element()};
function page(start=80, end=100, epoch='epoch') {
  return {thread_id: 'session', history: {epoch, start, end, total: end, before: start ? `${epoch}:${start}` : null},
    thread: {turns: Array.from({length: end-start}, (_, i) => ({id: `t${start+i}`, history_revision: 0}))}};
}
function fixture(fetchPage = async () => page(60,80)) {
  let renders = 0;
  const root = new Element();
  const errors = [];
  const view = new HistoryTimeline({root, fetchPage, onError: e => errors.push(e), renderTurn: (turn, node) => { renders++; return node || new Element(); }});
  return {view, root, errors, renders: () => renders};
}

test('first page renders 20 turns and streaming only updates changed turn', () => {
  const {view, root, renders} = fixture();
  const first = page(); view.update(first);
  const old = root.children[1];
  view.update(page());
  assert.equal(renders(), 20);
  const next = page(); next.thread.turns[19].history_revision++;
  view.update(next);
  assert.equal(renders(), 21);
  assert.equal(root.children[1], old);
});

test('prepend preserves reading position and retains existing node identity', async () => {
  const {view, root} = fixture();
  view.update(page()); root.scrollTop = 250;
  const anchor = view.anchor();
  const old = view.entries.get(anchor.id).node;
  await view.loadEarlier();
  assert.equal(view.entries.size, 40);
  assert.equal(old.getBoundingClientRect().top, anchor.top);
  assert.equal(view.before, 'epoch:60');
  view.showRecent();
  assert.equal(view.entries.size, 20);
});

test('session reset aborts and ignores stale history response', async () => {
  let complete; let signal;
  const {view} = fixture((_before, value) => { signal = value; return new Promise(resolve => complete = resolve); });
  view.update(page()); const pending = view.loadEarlier();
  view.reset(); view.update(page(0,3,'new'));
  assert.equal(signal.aborted, true);
  complete(page(60,80)); await pending;
  assert.equal(view.entries.size, 3);
  assert.equal(view.epoch, 'new');
});

test('failed request is retryable without losing current history', async () => {
  let count=0;
  const {view,errors} = fixture(async () => { if (!count++) throw Error('offline'); return page(60,80); });
  view.update(page()); await view.loadEarlier();
  assert.equal(view.entries.size, 20);
  assert.equal(view.loading, false);
  assert.equal(errors.length, 1);
  await view.loadEarlier(); assert.equal(view.entries.size, 40);
});

test('history reset and reconnect gaps do not leave misleading missing ranges', () => {
  const {view} = fixture(); view.update(page()); view.update(page(110,130));
  assert.equal(view.entries.size, 20);
  assert.equal(view.before, 'epoch:110');
  view.update(page(0,5,'reset'));
  assert.equal(view.entries.size, 5);
  assert.equal(view.before, null);
});

test('scrolling to top loads automatically and coalesces repeated scroll events', async () => {
  let complete; let requests = 0;
  const {view, root} = fixture(() => { requests++; return new Promise(resolve => complete = resolve); });
  view.update(page());
  assert.equal(view.more.hidden, true);
  root.scrollTop = 0;
  root.events.scroll(); root.events.scroll(); root.events.scroll();
  assert.equal(requests, 1);
  assert.match(view.label.textContent, /正在加载/);
  complete(page(60,80));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(view.entries.size, 40);
  assert.equal(view.loading, false);
});

test('automatic loading stops after an error until explicit retry', async () => {
  let requests = 0;
  const {view,root} = fixture(async () => { requests++; throw Error('offline'); });
  view.update(page()); root.scrollTop = 0; root.events.scroll();
  await new Promise(resolve => setImmediate(resolve));
  root.events.scroll();
  assert.equal(requests, 1);
  assert.equal(view.more.hidden, false);
  assert.equal(view.more.textContent, '重试加载历史');
});
