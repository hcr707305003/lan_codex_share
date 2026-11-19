const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');
function setup() {
  const el = (tag, cls, text) => ({tag, text, children:[], querySelectorAll() { return []; }, addEventListener(event, fn) { this[event] = fn; }, append(...nodes) { this.children.push(...nodes); }});
  const ctx = vm.createContext({enhanceActivityPre: () => {}, el, clipText: v => String(v), safeJson: v => JSON.stringify(v, null, 2)});
  vm.runInContext(source.slice(source.indexOf('function appendLabeledPre('), source.indexOf('function renderActivityBody(')), ctx);
  return {ctx, body:el('div')};
}
test('MCP text is shown verbatim with newlines and inert HTML; raw envelope remains available', () => {
  const {ctx,body}=setup();
  const value={content:[{type:'text',text:'line 1\n  <script>alert(1)</script>'}],isError:true};
  ctx.appendToolPayload(body,'结果',JSON.stringify(value));
  assert.equal(body.children[0].text,'工具执行失败');
  assert.equal(body.children[2].tag,'pre');
  assert.equal(body.children[2].text,value.content[0].text);
  const raw=body.children[3];
  assert.equal(raw.tag,'details');
  assert.equal(raw.children.length,1);
  raw.open=true;raw.toggle();raw.toggle();
  assert.equal(raw.children.length,2);
  assert.ok(raw.children[1].text.includes('"isError": true'));
});
test('mixed content retains order and non-text block information', () => {
 const {ctx,body}=setup();
 ctx.appendToolPayload(body,'结果',{content:[{type:'text',text:'first'},{type:'resource',resource:{text:'second'}},{type:'image',mimeType:'image/png',data:'abc'}]});
 assert.ok(body.children[1].text.startsWith('first\n\nsecond\n\n'));
 assert.ok(body.children[1].text.includes('image/png'));
 assert.ok(!body.children[1].text.includes('abc')); 
});
test('code arguments expand but preserve remaining arguments in raw details', () => {
 const {ctx,body}=setup();
 ctx.appendToolPayload(body,'参数',{code:'a();\nb();',title:'example'},true);
 assert.equal(body.children[1].text,'a();\nb();');
 body.children[2].open=true;body.children[2].toggle();
 assert.ok(body.children[2].children[1].text.includes('example'));
});
test('ordinary JSON, false, zero and plain strings are not discarded', () => {
 for(const value of [{count:1},false,0,'hello\nworld']) {
 const {ctx,body}=setup();ctx.appendToolPayload(body,'结果',value);
 assert.equal(body.children[1].text,typeof value==='string'?value:JSON.stringify(value,null,2));
 assert.equal(body.children.length,2);
 }
});
