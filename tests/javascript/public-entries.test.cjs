const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../lan_codex_share/web/app.js'), 'utf8');
const code = source.slice(source.indexOf('let publicEntryItems ='), source.indexOf('async function refreshPublicEntries'));

test('entry links preserve selected session and reject unsafe URLs', () => {
  const root = {replaceChildren(...items) { this.items = items; }};
  const context = vm.createContext({URL, selectedSessionId: 'session-1', document: {getElementById: () => root},
    el: () => ({setAttribute() {}, append() {}}), icon: () => ({})});
  vm.runInContext(code, context);
  vm.runInContext(`publicEntryItems = [{kind:'frp', origin:'https://frp.example'}, {kind:'cloudflare', origin:'javascript:alert(1)'}]; renderPublicEntries()`, context);
  assert.equal(root.items.length, 1);
  assert.equal(root.items[0].href, 'https://frp.example/?session=session-1');
  assert.equal(root.items[0].rel, 'noopener noreferrer');
  assert.equal(root.items[0].target, '_blank');
  vm.runInContext(`selectedSessionId = 'session-2'; renderPublicEntries()`, context);
  assert.equal(root.items[0].href, 'https://frp.example/?session=session-2');
  const link = root.items[0];
  vm.runInContext('renderPublicEntries()', context);
  assert.equal(root.items[0], link);
  vm.runInContext('publicEntryItems = []; renderPublicEntries()', context);
  assert.equal(root.hidden, true);
});
