const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/app.js'), 'utf8');
const authCode = source.slice(source.indexOf('async function authenticationStatus()'), source.indexOf('function displayTime('));
test('login status refreshes CSRF for pages left open across server restart', async () => {
  const context = vm.createContext({fetch: async () => ({ok: true,
    json: async () => ({required: true, authenticated: true}),
    headers: {get: key => key === 'X-CSRF-Token' ? 'new-server-token' : null},
  })});
  vm.runInContext('let csrf = "old-server-token";\n' + authCode, context);
  assert.equal((await context.authenticationStatus()).authenticated, true);
  assert.equal(vm.runInContext('csrf', context), 'new-server-token');
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
