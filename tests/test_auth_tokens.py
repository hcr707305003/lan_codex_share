import json
import os

import pytest

from lan_codex_share.auth_tokens import AuthTokens, LOGIN_MAX_AGE


def test_restart_expiry_and_independent_logins(tmp_path, monkeypatch):
    now = [1800000000]
    monkeypatch.setattr('lan_codex_share.auth_tokens.time.time', lambda: now[0])
    path = tmp_path / 'runtime' / 'auth.json'
    first = AuthTokens('团队密码', path)
    token = first.issue()
    assert token != first.issue()
    restarted = AuthTokens('团队密码', path)
    assert restarted.verify(token)
    now[0] += LOGIN_MAX_AGE - 1
    assert restarted.verify(token)
    now[0] += 1
    assert not restarted.verify(token)
    assert '团队密码' not in path.read_text(encoding='utf-8')
    if os.name != 'nt':
        assert path.stat().st_mode & 0o077 == 0


def test_password_changes_revoke_even_if_restored(tmp_path):
    path = tmp_path / 'auth.json'
    token = AuthTokens('old', path).issue()
    assert not AuthTokens('new', path).verify(token)
    assert not AuthTokens('old', path).verify(token)
    token = AuthTokens('old', path).issue()
    AuthTokens('', path)
    assert not AuthTokens('old', path).verify(token)
    assert not AuthTokens('old', tmp_path / 'other.json').verify(token)


def test_tampering_and_future_tokens_rejected(monkeypatch):
    now = [1800000000]
    monkeypatch.setattr('lan_codex_share.auth_tokens.time.time', lambda: now[0])
    auth = AuthTokens('secret')
    token = auth.issue()
    for invalid in ('', 'legacy-token', token + 'x', token.replace('v1', 'v2'), '😀', 'a.' * 3000):
        assert not auth.verify(invalid)
    parts = token.split('.')
    parts[2] = str(int(parts[2]) + 1)
    assert not auth.verify('.'.join(parts))
    now[0] -= 1
    assert not auth.verify(token)


@pytest.mark.parametrize('body', ['broken', 'null', '{}', '[]', '{"version":1,"key":"bad","password_tag":"bad"}'])
def test_corrupt_state_fails_closed(tmp_path, body):
    path = tmp_path / 'auth.json'
    path.write_text(body, encoding='utf-8')
    with pytest.raises(ValueError, match='登录状态'):
        AuthTokens('secret', path)
    assert path.read_text(encoding='utf-8') == body


def test_failed_rotation_preserves_old_state(tmp_path, monkeypatch):
    path = tmp_path / 'auth.json'
    token = AuthTokens('old', path).issue()
    original = json.loads(path.read_text())
    def fail(*args):
        raise PermissionError('read only')
    monkeypatch.setattr('lan_codex_share.auth_tokens.os.replace', fail)
    with pytest.raises(PermissionError):
        AuthTokens('new', path)
    assert json.loads(path.read_text()) == original
    assert AuthTokens('old', path).verify(token)
