const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

// Exercise the production renderer without starting the app or a Codex session.
class Node {
  constructor(tagName = '', text = '') {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.style = {};
    this.attributes = {};
    this.text = text;
  }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}

const source = fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');
const context = vm.createContext({document: {
  createElement: tag => new Node(tag),
  createTextNode: text => new Node('', text),
}});
vm.runInContext(
  source.slice(source.indexOf('function el('), source.indexOf('function icon('))
  + source.slice(source.indexOf('function parseLocalFileTarget('), source.indexOf('function fileEndpoint(')),
  context,
);
const render = text => context.renderMarkdown(text);
const all = (node, tag) => [
  ...(node.tagName === tag.toUpperCase() ? [node] : []),
  ...node.children.flatMap(child => all(child, tag)),
];

test('table interrupts a paragraph and renders semantic headers, rows and alignment', () => {
  const root = render('说明\n| 问题 | 当前情况 | 调整方向 |\n| :--- | :---: | ---: |\n| 假期 | 未同步 | 修复 |\n\n下一段');
  assert.equal(all(root, 'table').length, 1);
  assert.deepEqual(all(root, 'th').map(cell => cell.textContent), ['问题', '当前情况', '调整方向']);
  assert.deepEqual(all(root, 'th').map(cell => cell.style.textAlign), ['left', 'center', 'right']);
  assert.ok(all(root, 'th').every(cell => cell.scope === 'col'));
  assert.equal(all(root, 'tbody')[0].children.length, 1);
  assert.deepEqual(all(root, 'p').map(node => node.textContent), ['说明', '下一段']);
  const wrapper = root.children[1];
  assert.equal(wrapper.className, 'markdown-table-scroll');
  assert.equal(wrapper.tabIndex, 0);
  assert.equal(wrapper.attributes.role, 'region');
});

test('optional outer pipes, escaped pipes, empty and uneven rows', () => {
  const root = render('名称 | 值\r\n--- | ---\r\nA\\|B | `x\\|y`\r\n| 短行 |\r\n| | |\r\n多余 | 保留 | 忽略');
  const rows = all(root, 'tbody')[0].children;
  assert.deepEqual(rows.map(row => row.children.map(cell => cell.textContent)), [
    ['A|B', 'x|y'], ['短行', ''], ['', ''], ['多余', '保留'],
  ]);
  assert.equal(all(root, 'code')[0].textContent, 'x|y');
});

test('cells retain rich text and safe file links; arbitrary HTML is inert', () => {
  const root = render('| 内容 |\n| --- |\n| **重点 `代码`**<br>下一行 [文件](C:/project/readme.md:12) |\n| <img src=x onerror=alert(1)> [危险](javascript:alert) `<br>` |');
  assert.equal(all(root, 'strong')[0].textContent, '重点 代码');
  assert.equal(all(root, 'br').length, 1);
  assert.equal(all(root, 'code')[1].textContent, '<br>');
  assert.equal(all(root, 'a').length, 1);
  assert.equal(all(root, 'a')[0].className, 'local-file-link');
  assert.equal(all(root, 'img').length, 0);
  assert.match(all(root, 'td')[1].textContent, /<img src=x onerror=alert\(1\)>/);
});

test('ordinary pipes, malformed headers and code fences remain unchanged', () => {
  for (const text of ['A | B\n普通文本', 'A | B\n--- | x', 'A | B\n| --- |', '```md\n| A | B |\n| --- | --- |\n```']) {
    assert.equal(all(render(text), 'table').length, 0, text);
  }
  assert.equal(all(render('```md\n| A |\n| --- |\n```'), 'code')[0].textContent, '| A |\n| --- |');
});

test('streamed prefixes are safe; completed delimiter and rows become a table', () => {
  const text = '| A | B |\n| --- | --- |\n| 内容 | 继续 |';
  for (let end = 0; end <= text.length; end += 1) assert.doesNotThrow(() => render(text.slice(0, end)));
  assert.equal(all(render('| A | B |\n| --- | --'), 'table').length, 0);
  assert.equal(all(render(text), 'td').length, 2);
});

test('table ends before other blocks containing pipes and supports multiple tables', () => {
  const root = render('| A |\n| --- |\n| B |\n# 标题 | 文本\n- 列表 | 文本\n> 引用 | 文本\n\n| C |\n| --- |\n| D |');
  assert.equal(all(root, 'table').length, 2);
  assert.equal(all(root, 'h1').length, 1);
  assert.equal(all(root, 'li').length, 1);
  assert.equal(all(root, 'blockquote').length, 1);
});
