const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../lan_codex_share/web/app.js'),'utf8');
function load(extra={}) { const c=vm.createContext(extra);vm.runInContext(source.slice(source.indexOf('async function copyActivityText('),source.indexOf('function appendLabeledPre(')),c);return c; }
test('search treats symbols literally, preserves Unicode offsets and handles empty/missing queries',()=>{
 const c=load();
 assert.deepEqual([...c.activityMatches('中文.*\n中文.*','.*')],[2,7]);
 assert.deepEqual([...c.activityMatches('aaa','aa')],[0]);
 assert.equal(c.activityMatches('text','').length,0);
 assert.equal(c.activityMatches('text','TEXT').length,0);
});
test('copy writes original multiline text',async()=>{
 let result;const c=load({navigator:{clipboard:{writeText:async text=>{result=text;}}}});
 await c.copyActivityText('a\n  <b>');assert.equal(result,'a\n  <b>');
});
test('LAN fallback cleans up and restores focus, including copy failure',async()=>{
 for(const success of [true,false]) {
 let removed=false,restored=false,selected=false;
 const node={focus(){},select(){selected=true;},remove(){removed=true;}};
 const c=load({navigator:{},el:()=>node,document:{activeElement:{focus(){restored=true;}},body:{append(){}},execCommand:()=>success}});
 if(success) await c.copyActivityText('hello');else await assert.rejects(c.copyActivityText('hello'));
 assert.equal(node.value,'hello');assert.ok(removed&&restored&&selected);
 }
});
test('context menu scopes selection, copies visible block, closes and preserves Shift browser menu',()=>{
 let menu,focused,prevented=false,copied,managed=false;
 class N {
  constructor(text){this.text=text;this.children=[];this.handlers={};this.style={};this.offsetWidth=216;this.offsetHeight=120;}
  setAttribute(){} append(n){this.children.push(n);} addEventListener(k,f){this.handlers[k]=f;}
  querySelectorAll(){return this.children.filter(n=>!n.disabled);} focus(){focused=this;}
  contains(n){return this.children.includes(n);} remove(){this.removed=true;}
 }
 const selectedNode={};
 const pre={contains:n=>n===selectedNode,getBoundingClientRect:()=>({left:10,top:10})};
 const document={activeElement:null,body:{append:n=>{menu=n;}},addEventListener(){}};
 const window={innerWidth:800,innerHeight:600,addEventListener(){},getSelection:()=>({anchorNode:selectedNode,focusNode:selectedNode,toString:()=> 'chosen'})};
 const c=load({document,window,AbortController,el:(tag,cls,text)=>new N(text)});
 const actions={text:'whole',search(){},copy:t=>{copied=t;},manageHistory(){managed=true;}};
 c.showActivityMenu({shiftKey:true},pre,actions);assert.equal(menu,undefined);
 c.showActivityMenu({clientX:799,clientY:599,preventDefault(){prevented=true;}},pre,actions);
 assert.ok(prevented);assert.equal(menu.children[0].text,'在会话中搜索选中文字');assert.equal(focused,menu.children[0]);
 assert.equal(menu.style.left,'580px');
 menu.children[1].handlers.click();assert.equal(copied,'chosen');assert.ok(menu.removed);
 window.getSelection=()=>null;
 c.showActivityMenu({clientX:20,clientY:20,preventDefault(){}},pre,actions);
 assert.ok(menu.children[1].disabled);
 menu.children[2].handlers.click();assert.equal(copied,'whole');
 c.showActivityMenu({clientX:20,clientY:20,preventDefault(){}},pre,actions);
 assert.equal(menu.children[3].text,'多选删除记录…');
 menu.children[3].handlers.click();assert.ok(managed);assert.ok(menu.removed);
});
