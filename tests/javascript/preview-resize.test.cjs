const {test} = require('node:test');
const assert = require('node:assert/strict');
const {bounds, createPreviewResize} = require('../../lan_codex_share/web/preview-resize.js');

class Target {
  constructor() { this.events = {}; this.attrs = {}; this.classes = new Set(); this.classList = {
    contains: n => this.classes.has(n), add: n => this.classes.add(n), remove: n => this.classes.delete(n)}; }
  addEventListener(n, fn) { (this.events[n] ||= new Set()).add(fn); }
  removeEventListener(n, fn) { this.events[n]?.delete(fn); }
  fire(n, values={}) { for (const fn of this.events[n] || []) fn({button:0,pointerId:1,preventDefault(){},...values}); }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  setPointerCapture(id) { this.capture = id; }
  hasPointerCapture(id) { return this.capture === id; }
  releasePointerCapture() { this.capture = null; }
}
function setup(saved=null, broken=false) {
  const win = new Target(), shell = new Target(), panel = new Target(), handle = new Target();
  win.innerWidth=1440; shell.classes.add('preview-open');
  shell.querySelector=()=>({getBoundingClientRect:()=>({width:248})});
  shell.style={setProperty:(n,v)=>{shell.width=parseFloat(v);},removeProperty:()=>{shell.width=null;}};
  const storage={getItem:()=>saved,setItem:(k,v)=>{if(broken)throw Error(); saved=v;},removeItem:()=>{saved=null;}};
  if(broken) Object.defineProperty(win,'localStorage',{get(){throw Error();}});
  const control=createPreviewResize({shell,panel,handle,window:win,...(broken?{}:{storage})});
  return {win,shell,handle,control,saved:()=>saved};
}
test('bounds match desktop, overlay and phone',()=>{
  assert.deepEqual(bounds(1440,248),{min:360,max:832,defaultWidth:648,mobile:false});
  assert.equal(bounds(1000,248).defaultWidth,640);
  assert.equal(bounds(375,248).mobile,true);
});
test('drag clamps width, saves on release and clears capture',()=>{
  const s=setup(); s.handle.fire('pointerdown',{clientX:800});
  s.handle.fire('pointermove',{clientX:500}); assert.equal(s.shell.width,832);
  s.handle.fire('pointerup'); assert.equal(s.saved(),'832'); assert.equal(s.handle.capture,null);
  s.handle.fire('keydown',{key:'ArrowRight'}); assert.equal(s.shell.width,812);
  s.handle.fire('dblclick'); assert.equal(s.shell.width,648); assert.equal(s.saved(),null);
});
test('cancel, blur and close restore preference without saving',()=>{
  const s=setup('700');
  for(const end of ['pointercancel','lostpointercapture','blur','close']) {
    s.shell.classes.add('preview-open'); s.handle.fire('pointerdown',{clientX:800});
    s.handle.fire('pointermove',{clientX:1000});
    if(end==='blur')s.win.fire('blur');
    else if(end==='close'){s.shell.classes.delete('preview-open');s.control.refresh();}
    else s.handle.fire(end);
    assert.equal(s.saved(),'700');assert.equal(s.shell.width,700);
    assert.equal(s.shell.classes.has('preview-resizing'),false);
  }
});
test('resize and mobile never overwrite preference; Home resets it',()=>{
  const s=setup('1000'); assert.equal(s.shell.width,832);
  s.win.innerWidth=375;s.win.fire('resize');assert.equal(s.shell.width,null);
  s.handle.fire('keydown',{key:'ArrowLeft'}); assert.equal(s.saved(),'1000');
  s.win.innerWidth=1920;s.win.fire('resize');assert.equal(s.shell.width,1000);
  s.handle.fire('keydown',{key:'Home'});assert.equal(s.shell.width,760);assert.equal(s.saved(),null);
});
test('invalid or unavailable storage is harmless; destroy removes listeners',()=>{
  for(const value of ['bad','Infinity','-10','0','']) assert.equal(setup(value).shell.width,648);
  const s=setup(null,true);s.handle.fire('keydown',{key:'ArrowLeft'});assert.equal(s.shell.width,668);
  s.control.destroy();s.handle.fire('keydown',{key:'ArrowLeft'});assert.equal(s.shell.width,668);
});
