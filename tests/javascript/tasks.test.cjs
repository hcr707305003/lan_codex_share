const {test} = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const {candidateUrl, newRequestId, LatestRequest} = require('../../lan_codex_share/web/tasks.js');

test('candidate URL encodes search and only a bounded cursor', () => {
  assert.equal(candidateUrl('A&B', '50'), '/api/sessions/candidates?q=A%26B&cursor=50');
  assert.equal(candidateUrl('', null), '/api/sessions/candidates?q=');
});
test('request IDs work without secure-context randomUUID on LAN HTTP', () => {
  const crypto = {getRandomValues: a => webcrypto.getRandomValues(a)};
  const first = newRequestId(crypto);
  assert.match(first, /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
  assert.notEqual(newRequestId(crypto), first);
});
test('late response cannot replace new query; closing aborts current query', async () => {
  const gate = new LatestRequest();
  const first = gate.next();
  const second = gate.next();
  assert.equal(first.signal.aborted, true);
  assert.equal(gate.isCurrent(first), false);
  assert.equal(gate.isCurrent(second), true);
  gate.cancel();
  assert.equal(second.signal.aborted, true);
  assert.equal(gate.isCurrent(second), false);
});
