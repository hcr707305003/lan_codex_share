"""Persistent signing state and fixed-lifetime browser login credentials."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time


LOGIN_MAX_AGE = 30 * 24 * 60 * 60
_HEX_KEY = re.compile(r'[0-9a-f]{64}')
_TOKEN = re.compile(r'v1\.(\d{1,12})\.(\d{1,12})\.([0-9a-f]{32})\.([0-9a-f]{64})', re.ASCII)


class AuthTokens:
    def __init__(self, password: str, state_path: Path | None = None):
        self._key = secrets.token_bytes(32)
        if state_path is None:
            return
        path = Path(state_path)
        exists = True
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            saved = None
            exists = False
        except (ValueError, UnicodeError) as exc:
            raise ValueError('登录状态文件损坏，请恢复备份或删除该文件后重新登录') from exc
        if exists:
            if (not isinstance(saved, dict) or saved.get('version') != 1
                    or not isinstance(saved.get('key'), str) or not _HEX_KEY.fullmatch(saved['key'])
                    or not isinstance(saved.get('password_tag'), str)
                    or not _HEX_KEY.fullmatch(saved['password_tag'])):
                raise ValueError('登录状态文件格式无效，请恢复备份或删除该文件后重新登录')
            key = bytes.fromhex(saved['key'])
            if hmac.compare_digest(saved['password_tag'], self._password_tag(key, password)):
                self._key = key
                return
        # Password changes (including disabling it) rotate the signing key.
        # The launcher holds its single-instance lock before calling this.
        data = {'version': 1, 'key': self._key.hex(),
                'password_tag': self._password_tag(self._key, password)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.auth-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _password_tag(key: bytes, password: str) -> str:
        return hmac.new(key, b'password\0' + password.encode('utf-8'), hashlib.sha256).hexdigest()

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, b'login\0' + payload.encode('ascii'), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        issued = int(time.time())
        payload = f'v1.{issued}.{issued + LOGIN_MAX_AGE}.{secrets.token_hex(16)}'
        return f'{payload}.{self._sign(payload)}'

    def verify(self, token: str) -> bool:
        if not isinstance(token, str) or len(token) > 160:
            return False
        match = _TOKEN.fullmatch(token)
        if not match:
            return False
        issued, expires = int(match[1]), int(match[2])
        now = time.time()
        return (issued <= now < expires and expires - issued == LOGIN_MAX_AGE
                and hmac.compare_digest(match[4], self._sign(token.rsplit('.', 1)[0])))
