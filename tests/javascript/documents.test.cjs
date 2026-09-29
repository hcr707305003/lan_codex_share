const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');

function setup() {
  const notices = [], sent = [];
  const context = vm.createContext({
    selectedFiles: [], sendingMessage: false, selectedSessionId: 'session-a',
    documentExtensions: new Set(['md', 'txt', 'docx', 'pdf']),
    allowedImageTypes: new Set(['image/png', 'image/jpeg', 'image/webp']),
    maxDocumentBytes: 20 * 1024 * 1024, maxDocuments: 5,
    maxImages: 4, maxImageBytes: 10 * 1024 * 1024, maxRequestBytes: 256 * 1024 * 1024,
    input: {value: 'question', disabled: false}, imageInput: {value: '', disabled: false},
    sendButton: {disabled: false, setAttribute() {}, removeAttribute() {}},
    renderPreviews() {}, updateSendState() {}, autoGrow() {},
    fileToPayload: async file => ({name: file.name}),
    mutateForSession: async (...args) => sent.push(args), refresh: async () => {},
    setNotice: (...args) => notices.push(args),
  });
  vm.runInContext(
    source.slice(source.indexOf('function fileExtension('), source.indexOf('function autoGrow('))
    + source.slice(source.indexOf('async function sendCurrentMessage('), source.indexOf('function closeMenu(')), context);
  return {context, notices, sent};
}

const file = (name, type = '', size = 128) => ({name, type, size});

test('document MIME may be empty; image and document counts are independent', () => {
  const {context, notices} = setup();
  context.addImageFiles(Array.from({length: 5}, (_, i) => file(`note${i}.MD`)));
  context.addImageFiles(Array.from({length: 4}, (_, i) => file(`image${i}.png`, 'image/png')));
  assert.equal(context.selectedFiles.length, 9);
  context.addImageFiles([file('too-many.docx')]);
  assert.equal(context.selectedFiles.length, 9);
  assert.match(notices.at(-1)[0], /最多/);
});

test('invalid format, empty and oversized documents do not enter the draft', () => {
  const {context, notices} = setup();
  context.addImageFiles([file('old.doc'), file('a.pdf', '', 0), file('huge.md', '', 21 * 1024 * 1024)]);
  assert.equal(context.selectedFiles.length, 0);
  assert.match(notices.at(-1)[0], /DOCX/);
  assert.match(notices.at(-1)[0], /超过/);
});

test('captured session and one in-flight request for mixed attachments', async () => {
  const {context, sent} = setup();
  context.selectedFiles = [file('a.pdf'), file('image.png', 'image/png')];
  let release;
  context.fileToPayload = item => new Promise(resolve => { release = () => resolve({name: item.name}); });
  const pending = context.sendCurrentMessage();
  await context.sendCurrentMessage();
  context.addImageFiles([file('late.md')]);
  assert.equal(context.selectedFiles.length, 2);
  context.selectedSessionId = 'session-b';
  release();
  // The second FileReader resolves immediately in this test.
  context.fileToPayload = async item => ({name: item.name});
  await pending;
  assert.equal(sent.length, 1);
  assert.equal(sent[0][1], 'session-a');
  assert.equal(sent[0][2].documents[0].name, 'a.pdf');
  assert.equal(sent[0][2].images[0].name, 'image.png');
  assert.equal(context.selectedFiles.length, 0);
});

test('parse failure retains text and attachments and unlocks the composer', async () => {
  const {context, notices} = setup();
  context.selectedFiles = [file('broken.docx')];
  context.mutateForSession = async () => { throw new Error('文档损坏'); };
  await context.sendCurrentMessage();
  assert.equal(context.input.value, 'question');
  assert.equal(context.selectedFiles[0].name, 'broken.docx');
  assert.equal(context.input.disabled, false);
  assert.equal(context.sendingMessage, false);
  assert.deepEqual(notices.at(-1), ['文档损坏', true]);
});
