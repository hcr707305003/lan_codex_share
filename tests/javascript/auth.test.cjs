const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');
const authCode = source.slice(source.indexOf('async function authenticationStatus()'), source.indexOf('function displayTime('));
test('login status refreshes CSRF for pages left open across server restart', async () => {
  const enabled = [];
  const context = vm.createContext({taskNotifications: {setEnabled: value => enabled.push(value)}, fetch: async () => ({ok: true,
    json: async () => ({required: true, authenticated: true}),
    headers: {get: key => key === 'X-CSRF-Token' ? 'new-server-token' : null},
  })});
  vm.runInContext('let csrf = "old-server-token";\n' + authCode, context);
  assert.equal((await context.authenticationStatus()).authenticated, true);
  assert.equal(vm.runInContext('csrf', context), 'new-server-token');
  assert.deepEqual(enabled, [false]);
  // Production reconnect handler must run the status refresh, not just initial bootstrap.
  assert.match(source.slice(source.indexOf('source.onopen ='), source.indexOf('source.onerror =')), /await authenticationStatus\(\)/);
});

test('failed status requests never overwrite the current CSRF token', async () => {
  const context = vm.createContext({fetch: async () => ({ok: false,
    json: async () => ({error: 'offline'}), headers: {get: () => 'invalid'},
  })});
  vm.runInContext('let csrf = "current";\n' + authCode, context);
  await assert.rejects(context.authenticationStatus(), /offline/);
  assert.equal(vm.runInContext('csrf', context), 'current');
});

test('notification setting enabled only for authenticated true boolean', async () => {
  for (const [value, authenticated, expected] of [[true,true,true],[true,false,false],['true',true,false],[false,true,false]]) {
    const calls=[];
    const context=vm.createContext({taskNotifications:{setEnabled:value=>calls.push(value)},fetch:async()=>({ok:true,
      json:async()=>({required:true,authenticated,notify_on_task_complete:value}),headers:{get:()=>null}})});
    vm.runInContext('let csrf="test";\n'+authCode, context);
    await context.authenticationStatus();
    assert.deepEqual(calls,[expected]);
  }
});

test('password login obtains settings before starting realtime baseline', async () => {
  const calls=[];
  const context=vm.createContext({
    authForm:{addEventListener:(name,handler)=>{context.submit=handler;}},
    authSubmit:{disabled:false,setAttribute(){},removeAttribute(){}},
    authMessage:{classList:{remove(){},add(){}},textContent:''},
    authPassword:{value:'fake',select(){}},csrf:'test',
    fetch:async()=>({ok:true,json:async()=>({authenticated:true})}),
    authenticationStatus:async()=>{calls.push('settings');},
    startAuthenticatedApp:async()=>{calls.push('start');},
  });
  const start=source.indexOf("authForm.addEventListener('submit'");
  vm.runInContext(source.slice(start, source.indexOf('\nupdateSendState();',start)),context);
  await context.submit({preventDefault(){}});
  assert.deepEqual(calls,['settings','start']);
});
