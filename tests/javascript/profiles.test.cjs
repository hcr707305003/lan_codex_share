const {test} = require('node:test');
const assert = require('node:assert/strict');
const {isDirty, validate} = require('../../lan_codex_share/web/profiles.js');
test('profile drafts retain exact Markdown whitespace', () => {
  const record = {alias: '', notice_markdown: '# Heading\n'};
  assert.equal(isDirty(record, '', '# Heading\n'), false);
  assert.equal(isDirty(record, '', '# Heading'), true);
  assert.equal(isDirty(record, 'Project', '# Heading\n'), true);
});
test('notice limits use UTF8 and aliases reject controls', () => {
  assert.equal(validate('', '中'.repeat(21000)), '');
  assert.ok(validate('', '中'.repeat(22000)));
  assert.ok(validate('a\nb', ''));
  assert.ok(validate('a'.repeat(101), ''));
  assert.equal(validate('', ''), '');
});
