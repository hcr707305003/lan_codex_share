const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');
class Node {
  constructor() { this.children = []; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  addEventListener() {}
}
test('waiting queue excludes failed, active and completed records and hides when cleared', () => {
  const c = vm.createContext({queuePanel: {}, queueCount: {}, queueList: new Node(),
    document: {createDocumentFragment: () => new Node()}, el: () => new Node(),
    statusValue: value => value, userText: item => item.text || '', imageRecords: () => [], displayTime: () => ''});
  vm.runInContext(source.slice(source.indexOf('function renderQueue('), source.indexOf('async function cancelQueuedMessage(')), c);
  const records = [{id:'1',status:'failed'}, {id:'2',status:'processing'}, {id:'3',status:'queued'}, {id:'4',status:'completed'}];
  c.renderQueue(records);
  assert.equal(c.queueCount.textContent, '1 条消息');
  assert.equal(c.queueList.children[0].children.length, 1);
  c.renderQueue(records.filter(item => item.status !== 'queued'));
  assert.equal(c.queuePanel.hidden, true);
  assert.equal(c.queueList.children.length, 0);
  assert.equal(records.length, 4);
});
