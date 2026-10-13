const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createArchivePreview} = require('../../lan_codex_share/web/archive-preview.js');

class Element {
  constructor(tag, text='') { this.tagName=tag; this.text=text; this.children=[]; this.events={}; this.attrs={}; }
  set textContent(v) { this.text=String(v); this.children=[]; }
  get textContent() { return this.text+this.children.map(c=>c.textContent).join(''); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; this.text=''; }
  setAttribute(k,v) { this.attrs[k]=v; }
  addEventListener(k,v) { this.events[k]=v; }
  focus() {}
}
const find = (node, predicate) => [node, ...node.children.flatMap(c=>find(c, predicate))].filter(predicate);
const json = data => ({ok:true,headers:{get:()=> 'application/json'},json:async()=>data});
function setup(fetcher) {
  const container = new Element('div'), requests=[], revoked=[];
  const host = {container, document:{createElement:t=>new Element(t)},
    fetch: async (url, options) => { requests.push({url,options}); return fetcher(url,options); },
    url:{createObjectURL:()=> 'blob:test',revokeObjectURL:u=>revoked.push(u)},
    renderMarkdown:text=>new Element('article',text), onUnauthorized:()=>false};
  return {viewer:createArchivePreview(host), container, requests, revoked};
}
const listing = {version:'v1',directory:'',page:0,total:1,entries:[{id:0,name:'说明.md',path:'说明.md',directory:false,size:10}]};

test('pagination and empty directory preserve navigation state', async()=>{
  const s=setup(url=>{
    const query=new URL(url,'http://localhost').searchParams;
    return json(query.get('directory') ? {version:'v1',entries:[],total:0} :
      {version:'v1',total:101,entries:[{name:'目录',path:'目录/',directory:true}]});
  });
  await s.viewer.open({path:'sample.zip'});
  await find(s.container,n=>n.tagName==='button'&&n.text==='下一页')[0].events.click();
  assert.match(s.requests.at(-1).url,/page=1/);
  assert.match(s.requests.at(-1).url,/version=v1/);
  await find(s.container,n=>n.tagName==='button'&&n.text==='目录')[0].events.click();
  assert.match(s.container.textContent,/此目录为空/);
  await find(s.container,n=>n.tagName==='button'&&n.text==='ZIP 根目录')[0].events.click();
  assert.match(s.requests.at(-1).url,/page=0/);
});

test('directory and member links preserve ZIP version and separate full download', async()=>{
  const s=setup(url=>json(url.includes('/list?')?listing:{kind:'markdown',name:'说明.md',content:'# hello',size:10}));
  await s.viewer.open({path:'C:/sample.zip'});
  await find(s.container,n=>n.tagName==='button'&&n.text==='说明.md')[0].events.click();
  assert.match(s.requests.at(-1).url,/version=v1/);
  assert.match(s.container.textContent,/# hello/);
  const links=find(s.container,n=>n.tagName==='a');
  assert.ok(links.some(n=>n.href.startsWith('/api/files/download?')));
  assert.ok(links.some(n=>n.href.includes('/api/archives/download?')&&n.href.includes('member=0')));
});

test('late response and abort cannot reopen a closed pane', async()=>{
  let resolve; const s=setup(()=>new Promise(r=>resolve=r));
  const pending=s.viewer.open({path:'C:/sample.zip'});
  s.viewer.close(); resolve(json(listing)); await pending;
  assert.equal(s.container.children.length,0);
  assert.equal(s.requests[0].options.signal.aborted,true);
});

test('spreadsheet values are inert; switching sheets does not change download', async()=>{
  const s=setup(url=>json(url.includes('/list?')?listing:{kind:'spreadsheet',name:'x.xlsx',sheets:['一','二'],sheet:0,rows:[['<script>bad()</script>']],truncated:true}));
  await s.viewer.open({path:'C:/sample.zip'});
  await find(s.container,n=>n.tagName==='button'&&n.text==='说明.md')[0].events.click();
  assert.equal(find(s.container,n=>n.tagName==='script').length,0);
  assert.match(s.container.textContent,/<script>bad/);
  assert.match(s.container.textContent,/截断/);
  const select=find(s.container,n=>n.tagName==='select')[0];
  select.value='1'; await select.events.change();
  assert.match(s.requests.at(-1).url,/sheet=1/);
});

test('download remains available on preview failure and object URLs are revoked', async()=>{
  let media=false;
  const s=setup(url=>url.includes('/list?')?json(listing):media?
    {ok:true,headers:{get:()=> 'image/png'},blob:async()=>({})}:
    {ok:false,status:413,json:async()=>({error:'超限'})});
  await s.viewer.open({path:'C:/sample.zip'});
  await find(s.container,n=>n.tagName==='button'&&n.text==='说明.md')[0].events.click();
  assert.match(s.container.textContent,/超限/);
  assert.ok(find(s.container,n=>n.tagName==='a'&&n.text==='下载此文件').length);
  media=true; await s.viewer.open({path:'C:/sample.zip'});
  await find(s.container,n=>n.tagName==='button'&&n.text==='说明.md')[0].events.click();
  s.viewer.close(); assert.deepEqual(s.revoked,['blob:test']);
});

test('PDF uses a compact toolbar and dedicated full-height content, reset on return', async()=>{
  const pdfListing={...listing,entries:[{...listing.entries[0],name:'通知书.pdf'}]};
  const s=setup(url=>url.includes('/list?')?json(pdfListing):
    {ok:true,headers:{get:()=> 'application/pdf'},blob:async()=>({})});
  await s.viewer.open({path:'C:/sample.zip'});
  await find(s.container,n=>n.tagName==='button'&&n.text==='通知书.pdf')[0].events.click();
  const toolbar=find(s.container,n=>n.className==='archive-toolbar')[0];
  const back=find(toolbar,n=>n.tagName==='button'&&n.text==='返回文件列表')[0];
  assert.ok(back, 'return control belongs in toolbar, not above PDF');
  assert.equal(find(toolbar,n=>n.tagName==='nav').length,1);
  assert.equal(find(toolbar,n=>n.tagName==='a').length,2);
  const content=find(s.container,n=>n.className==='archive-content archive-content-pdf')[0];
  assert.ok(content);
  assert.equal(content.children.length,1,'no constant warning taking up document space');
  const object=content.children[0];
  assert.equal(object.tagName,'object');
  assert.equal(object.type,'application/pdf');
  assert.equal(object.data,'blob:test');
  assert.equal(object.title,'通知书.pdf');
  assert.match(object.textContent,/无法内嵌显示 PDF/);
  await back.events.click();
  assert.equal(find(s.container,n=>n.className==='archive-content archive-content-pdf').length,0);
  assert.deepEqual(s.revoked,['blob:test']);
});
