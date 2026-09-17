import hashlib
import io
import json
import threading
import zipfile

import pytest

from lan_codex_share.desktop import installer


def test_latest_release_uses_official_latest_endpoint(monkeypatch):
    seen = []
    release = {'tag_name': 'v1.2.3', 'assets': [], 'draft': False, 'prerelease': False}

    def download(url, limit, cancel, progress):
        seen.append(url)
        return json.dumps(release).encode()

    monkeypatch.setattr(installer, 'download', download)
    assert installer.latest_release() == release
    assert seen == ['https://api.github.com/repos/fatedier/frp/releases/latest']


def test_platform_mapping():
    assert installer.platform_key('Windows', 'AMD64') == 'windows_amd64'
    assert installer.platform_key('Darwin', 'arm64') == 'darwin_arm64'


def test_installs_only_verified_binary(tmp_path, monkeypatch):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('frp_1.2.3_windows_amd64/frpc.exe', b'fake-test-executable')
    payload = data.getvalue()
    release = {'tag_name': 'v1.2.3', 'assets': [{'name': 'frp_1.2.3_windows_amd64.zip',
               'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(),
               'browser_download_url': 'https://github.com/fatedier/frp/releases/download/v1.2.3/test.zip'}]}
    monkeypatch.setattr(installer, 'platform_key', lambda: 'windows_amd64')
    monkeypatch.setattr(installer, 'download', lambda url, limit, cancel, progress: payload)
    binary = installer.install_frpc(release, tmp_path, threading.Event(), lambda message: None)
    assert binary.read_bytes() == b'fake-test-executable'
    release['assets'][0]['digest'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='校验'):
        installer.install_frpc(release, tmp_path, threading.Event(), lambda message: None)
    assert binary.read_bytes() == b'fake-test-executable'


@pytest.mark.parametrize('name', ['../../frpc.exe', '/frpc.exe', 'x/../frpc.exe'])
def test_archive_path_rejected(tmp_path, name):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr(name, b'test')
    with pytest.raises(ValueError):
        installer.extract_binary(data.getvalue(), 'zip', 'frpc.exe')


@pytest.mark.parametrize('url', ['http://github.com/a', 'https://evil.example/a', 'https://github.com@evil.example/a'])
def test_untrusted_download_origin_rejected(url):
    with pytest.raises(ValueError):
        installer.validate_url(url)


def test_missing_digest_refuses_install(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, 'platform_key', lambda: 'windows_amd64')
    release = {'tag_name': 'v1.2.3', 'assets': [{'name': 'frp_1.2.3_windows_amd64.zip'}]}
    with pytest.raises(ValueError, match='SHA-256'):
        installer.install_frpc(release, tmp_path, threading.Event(), lambda m: None)


def test_binary_size_limit(monkeypatch):
    monkeypatch.setattr(installer, 'MAX_BINARY', 1)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('frpc.exe', b'too big')
    with pytest.raises(ValueError):
        installer.extract_binary(data.getvalue(), 'zip', 'frpc.exe')


def test_zip_symlink_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        entry = zipfile.ZipInfo('frpc.exe')
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, 'outside')
    with pytest.raises(ValueError, match='链接'):
        installer.extract_binary(data.getvalue(), 'zip', 'frpc.exe')


def test_cancelled_download_does_not_connect(monkeypatch):
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(installer, 'build_opener', lambda *a: pytest.fail('must not contact network'))
    with pytest.raises(ValueError, match='取消'):
        installer.download(installer.API_URL, 100, cancel, lambda m: None)
