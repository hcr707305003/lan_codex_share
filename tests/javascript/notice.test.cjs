const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mount} = require('../../lan_codex_share/web/notice.js');
const project = {id: 'p', cwd: '/project', revision: 1, has_notice: true};
const tick = () => new Promise(resolve => setImmediate(resolve));
function element() {
  return {hidden: false, textContent: '', attrs: {}, children: [], handlers: {},
    setAttribute(k,v) {this.attrs[k] = v;}, addEventListener(k,v) {this.handlers[k] = v;},
    replaceChildren(...nodes) {this.children = nodes;}, click() {return this.handlers.click();},
    contains(target) {return target === this;}, focus() {this.focused = true;}};
}
function setup(request = async () => ({notice_markdown: '# Hello'}), overrides = {}) {
  const options = Object.fromEntries(['root','toggle','body','retry','status','edit','panel','close','document'].map(k => [k, element()]));
  const calls = [], edits = [];
  Object.assign(options, {request: (...args) => { calls.push(args); return request(...args); },
    markdown: value => value, layout: fn => fn(), editProject: p => edits.push(p)}, overrides);
  return {...options, calls, edits, controller: mount(options)};
}
test('default collapsed, lazy fetch, cached toggle and edit target', async () => {
  const c = setup(); c.controller.update('a', project);
  assert.equal(c.root.hidden, false); assert.equal(c.body.hidden, true); assert.equal(c.calls.length, 0);
  c.toggle.click(); await tick();
  assert.equal(c.toggle.attrs['aria-expanded'], 'true'); assert.deepEqual(c.body.children, ['# Hello']);
  c.controller.update('a', {...project}); c.toggle.click(); c.toggle.click(); await tick();
  assert.equal(c.calls.length, 1);
  c.edit.click(); assert.equal(c.edits[0].id, 'p');
  c.controller.update('b', project); assert.equal(c.body.hidden, true);
});
test('popover closes on outside pointer, Escape and close button without stealing outside focus', async () => {
  const c = setup(); c.controller.update('a', project); c.toggle.click(); await tick();
  assert.equal(c.panel.hidden, false);
  c.document.handlers.pointerdown({target: c.panel}); assert.equal(c.panel.hidden, false);
  c.document.handlers.pointerdown({target: element()}); assert.equal(c.panel.hidden, true);
  assert.equal(c.toggle.focused, undefined);
  c.toggle.click(); c.document.handlers.keydown({key:'Escape', preventDefault(){}, stopImmediatePropagation(){}});
  assert.equal(c.panel.hidden, true); assert.equal(c.toggle.focused, true);
  c.toggle.focused = false; c.toggle.click(); c.close.click();
  assert.equal(c.panel.hidden, true); assert.equal(c.toggle.focused, true);
});
test('rejected edit handoff retains notice; keyboard open focuses panel controls', async () => {
  const c = setup(undefined, {editProject: () => false});
  c.controller.update('a', project); c.toggle.handlers.click({detail:0}); await tick();
  assert.equal(c.close.focused, true);
  c.edit.click(); assert.equal(c.panel.hidden, false);
  c.controller.close(); assert.equal(c.panel.hidden, true);
});
test('late response never leaks across sessions', async () => {
  let resolve; const c = setup(() => new Promise(r => {resolve = r;}));
  c.controller.update('a', project); c.toggle.click();
  const signal = c.calls[0][1];
  c.controller.update('b', {...project, id: 'other'});
  resolve({notice_markdown: 'OLD'}); await tick();
  assert.equal(signal.aborted, true); assert.deepEqual(c.body.children, []); assert.equal(c.body.hidden, true);
});
test('revision updates expanded notice; deletion hides and new notice stays closed', async () => {
  let value = 'one'; const c = setup(async () => ({notice_markdown: value}));
  c.controller.update('a', project); c.toggle.click(); await tick();
  value = 'two'; c.controller.update('a', {...project, revision: 2}); await tick();
  assert.deepEqual(c.body.children, ['two']); assert.equal(c.body.hidden, false);
  c.controller.update('a', {...project, revision: 3, has_notice: false});
  assert.equal(c.root.hidden, true);
  c.controller.update('a', {...project, revision: 4}); assert.equal(c.body.hidden, true);
});
test('failure does not loop on snapshots; explicit retry recovers', async () => {
  let fail = true; const c = setup(async () => {if (fail) throw new Error('offline'); return {notice_markdown: 'ok'};});
  c.controller.update('a', project); c.toggle.click(); await tick();
  assert.equal(c.retry.hidden, false); assert.match(c.status.textContent, /offline/);
  c.controller.update('a', project); c.controller.update('a', project); await tick();
  assert.equal(c.calls.length, 1);
  fail = false; c.retry.click(); await tick(); assert.deepEqual(c.body.children, ['ok']);
});
test('missing project, no notice and whitespace response hide the banner', async () => {
  const c = setup(async () => ({notice_markdown: ' \n\t'}));
  c.controller.update('a', null); assert.equal(c.root.hidden, true);
  c.controller.update('a', {...project, has_notice: false}); assert.equal(c.root.hidden, true);
  c.controller.update('a', project); c.toggle.click(); await tick(); assert.equal(c.root.hidden, true);
});
test('collapsed revisions stay lazy and closing a pending read aborts it', async () => {
  let resolve; const c = setup(() => new Promise(r => {resolve = r;}));
  c.controller.update('a', project);
  c.controller.update('a', {...project, revision: 2}); assert.equal(c.calls.length, 0);
  c.toggle.click(); const oldSignal = c.calls[0][1]; c.toggle.click();
  resolve({notice_markdown: 'late'}); await tick();
  assert.equal(oldSignal.aborted, true); assert.deepEqual(c.body.children, []);
  c.toggle.click(); assert.equal(c.calls.length, 2);
  resolve({notice_markdown: 'new'}); await tick(); assert.deepEqual(c.body.children, ['new']);
});
