const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');

class Element {
  constructor(tag = '', text = '') {
    this.tagName = tag.toUpperCase(); this.text = text; this.children = []; this.attrs = {}; this.events = {};
    this.style = {}; this.dataset = {};
    const classes = new Set();
    this.classList = {add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value)};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ''; }
  set textContent(text) { this.text = String(text); this.children = []; }
  get textContent() { return this.text + this.children.map(node => node.textContent).join(''); }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; if (key === 'href') delete this.href; }
  addEventListener(event, fn) { this.events[event] = fn; }
  contains() { return false; }
  focus() {}
  blur() {}
}
const all = (node, tag) => [...(node.tagName === tag.toUpperCase() ? [node] : []), ...node.children.flatMap(child => all(child, tag))];
const jsonResponse = data => ({ok: true, headers: {get: () => 'application/json'}, json: async () => data});
const reference = {documentId: 'id', sessionId: 's', name: 'example.docx', size: 100};

function setup() {
  const context = vm.createContext({URLSearchParams, HTMLElement: Element,
    document: {createElement: tag => new Element(tag), createTextNode: text => new Element('', text)},
    requestAnimationFrame: fn => fn(), previewRequestId: 0, currentFileReference: null, previewReturnFocus: null,
    handleUnauthorized: () => false, selectedSessionId: 's', latestSnapshot: null,
    displayTime: () => '', statusValue: () => '', stateLabel: () => '',
    fetch: async () => jsonResponse({name: 'example.docx', kind: 'text', content: '<script>bad()</script>\nA\tB', warning: '文本预览，不保证还原原始版式。'}),
  });
  for (const key of ['appShell', 'mainPanel', 'filePreview', 'filePreviewTitle', 'filePreviewPath', 'filePreviewBody', 'filePreviewDownload', 'timeline']) context[key] = new Element();
  vm.runInContext(
    source.slice(source.indexOf('function el('), source.indexOf('function icon('))
    + source.slice(source.indexOf('function parseLocalFileTarget('), source.indexOf('function fileEndpoint('))
    + source.slice(source.indexOf('function fileEndpoint('), source.indexOf('function userText('))
    + source.slice(source.indexOf('function userText('), source.indexOf('function imageRecords('))
    + source.slice(source.indexOf('function renderUserMessage('), source.indexOf('function renderUserMessage(') + source.slice(source.indexOf('function renderUserMessage(')).indexOf('\nfunction ', 1))
    + source.slice(source.indexOf('function fileExtension('), source.indexOf('function addImageFiles(')), context);
  context.imageRecords = () => [];
  return context;
}

test('preview and download routes stay bound to captured Session; workspace route unchanged', () => {
  const c = setup();
  assert.equal(c.documentEndpoint(reference, true), '/api/documents/id/preview?session_id=s');
  c.selectedSessionId = 'changed';
  c.setFileDownload(reference);
  assert.equal(c.filePreviewDownload.href, '/api/documents/id?session_id=s');
  c.setFileDownload({path: 'C:/demo.md'});
  assert.equal(c.filePreviewDownload.href, '/api/files/download?path=C%3A%2Fdemo.md');
});

test('DOCX and TXT render inert text, not HTML or Markdown', async () => {
  const c = setup();
  await c.openFilePreview(reference);
  assert.equal(all(c.filePreviewBody, 'pre')[0].textContent, '<script>bad()</script>\nA\tB');
  assert.equal(all(c.filePreviewBody, 'script').length, 0);
  assert.match(c.filePreviewBody.textContent, /原始版式/);
});

test('opening a workspace Markdown after an attachment keeps the existing route and renderer', async () => {
  const c = setup();
  await c.openFilePreview(reference);
  let endpoint;
  c.fetch = async url => { endpoint = url; return jsonResponse({name: 'readme.md', relativePath: 'readme.md', kind: 'markdown', content: '# Workspace', size: 11}); };
  await c.openFilePreview({path: 'C:/demo/readme.md'});
  assert.equal(endpoint, '/api/files/view?path=C%3A%2Fdemo%2Freadme.md');
  assert.equal(all(c.filePreviewBody, 'h1')[0].textContent, 'Workspace');
  assert.equal(c.filePreviewDownload.href, '/api/files/download?path=C%3A%2Fdemo%2Freadme.md');
});

test('Markdown renders tables but no embedded HTML or remote images', async () => {
  const c = setup();
  c.fetch = async () => jsonResponse({kind: 'markdown', content: '| A |\n| --- |\n| B |\n<img src=x onerror=alert(1)>\n![image](https://example.org/test.png)'});
  await c.openFilePreview({...reference, name: 'a.md'});
  assert.equal(all(c.filePreviewBody, 'table').length, 1);
  assert.equal(all(c.filePreviewBody, 'img').length, 0);
});

test('late JSON cannot replace a new preview or reopen a closed panel', async () => {
  const c = setup();
  let resolve;
  c.fetch = async () => ({...jsonResponse({}), json: () => new Promise(done => { resolve = done; })});
  const old = c.openFilePreview(reference);
  await new Promise(setImmediate);
  c.fetch = async () => jsonResponse({kind: 'text', content: 'new'});
  await c.openFilePreview({...reference, documentId: 'new'});
  resolve({kind: 'text', content: 'old'});
  await old;
  assert.equal(c.filePreviewBody.textContent, 'new');
  c.fetch = async () => ({...jsonResponse({}), json: () => new Promise(done => { resolve = done; })});
  const pending = c.openFilePreview(reference);
  await new Promise(setImmediate);
  c.closeFilePreview();
  resolve({kind: 'text', content: 'late'});
  await pending;
  assert.equal(c.currentFileReference, null);
  assert.equal(c.filePreviewBody.children.length, 0);
  assert.equal(c.appShell.classList.contains('preview-open'), false);
});

test('sent name button and download are independent; draft and missing states', () => {
  const c = setup();
  const file = {id: 'id', name: 'notes.md', size: 5};
  const card = c.renderUserMessage({text: '', documents: [file]});
  assert.equal(all(card, 'button').length, 1);
  assert.equal(all(card, 'button')[0].attrs['aria-label'], '预览 notes.md');
  assert.equal(all(all(card, 'button')[0], 'a').length, 0);
  assert.equal(all(card, 'a')[0].download, file.name);
  const missing = c.renderUserMessage({text: '', documents: [{...file, missing: true}]});
  assert.equal(all(missing, 'button')[0].disabled, true);
  assert.equal(all(missing, 'a').length, 0);
  assert.equal(all(c.documentCard(file), 'button').length, 0);
});

test('PDF embeds session-bound URL and offers fallback; failed response has no content', async () => {
  const c = setup();
  c.fetch = async () => ({ok: true, headers: {get: () => 'application/pdf'}});
  await c.openFilePreview({...reference, name: 'a.pdf'});
  assert.equal(all(c.filePreviewBody, 'object')[0].data, '/api/documents/id/preview?session_id=s');
  assert.match(c.filePreviewBody.textContent, /下载/);
  c.fetch = async () => ({ok: false, json: async () => ({error: '文件不存在'})});
  await c.openFilePreview(reference);
  assert.equal(c.filePreviewBody.textContent, '文件不存在');
  assert.equal(c.filePreviewDownload.attrs['aria-disabled'], 'true');
});
