from pathlib import Path

import pytest

from lan_codex_share.desktop import discovery
from lan_codex_share.desktop.config import DesktopSettings


def binary(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'not executed')
    path.chmod(0o755)
    return path.resolve()


@pytest.fixture(autouse=True)
def no_path(monkeypatch):
    monkeypatch.setattr(discovery.shutil, 'which', lambda name: None)


def scan(name, roots, **kw):
    return discovery.discover(name, roots, system='Windows', machine='AMD64', **kw)


def test_roots_bin_depth_and_duplicates(tmp_path):
    expected = binary(tmp_path, 'bin/frp/v0.65.0/frpc.exe')
    binary(tmp_path, 'other/frpc.exe')
    binary(tmp_path, 'bin/a/b/c/d/frpc.exe')
    result = scan('frpc', [tmp_path, tmp_path])
    assert result.candidates == (expected,)
    assert not result.incomplete


def test_all_local_candidates_not_path_or_latest(tmp_path, monkeypatch):
    a = binary(tmp_path, 'frpc.exe')
    b = binary(tmp_path, 'bin/frp/v2/frpc.exe')
    monkeypatch.setattr(discovery.shutil, 'which', lambda _: str(tmp_path / 'external.exe'))
    assert set(scan('frpc', [tmp_path]).candidates) == {a, b}


def test_distribution_and_config_directories_both_searched(tmp_path):
    a = binary(tmp_path, 'app/cloudflared.exe')
    b = binary(tmp_path, 'config/bin/cloudflared/cloudflared.exe')
    assert set(scan('cloudflared', [tmp_path / 'app', tmp_path / 'config']).candidates) == {a, b}


@pytest.mark.parametrize('name,filename', [
    ('cloudflared', 'cloudflared-windows-amd64.exe'),
    ('frpc', 'frpc_windows_amd64.exe'),
])
def test_platform_names(tmp_path, name, filename):
    expected = binary(tmp_path, filename)
    for wrong in [f'{name}-windows-arm64.exe', f'{name}-linux-amd64',
                  f'{name}.zip', f'{name}-setup.exe', 'frps.exe']:
        binary(tmp_path, wrong)
    binary(tmp_path, f'bin/frp_0.65.0_linux_arm64/{name}.exe')
    assert scan(name, [tmp_path]).candidates == (expected,)


def test_path_fallback_and_usable(tmp_path, monkeypatch):
    expected = binary(tmp_path, 'external/frpc.exe')
    monkeypatch.setattr(discovery.shutil, 'which', lambda _: str(expected))
    assert scan('frpc', [tmp_path / 'missing']).candidates == (expected,)
    assert not discovery.usable(tmp_path)
    assert not discovery.usable(tmp_path / 'missing')


@pytest.mark.parametrize('system,filename', [('Linux', 'cloudflared-linux-arm64'), ('Darwin', 'cloudflared-darwin-arm64')])
def test_unix_platform_and_execute_permission(tmp_path, monkeypatch, system, filename):
    expected = binary(tmp_path, filename)
    monkeypatch.setattr(discovery.os, 'access', lambda *_: True)
    assert discovery.discover('cloudflared', [tmp_path], system=system, machine='aarch64').candidates == (expected,)
    monkeypatch.setattr(discovery.os, 'access', lambda *_: False)
    assert not discovery.discover('cloudflared', [tmp_path], system=system, machine='aarch64').candidates


def test_limit_does_not_auto_select_incomplete_scan(tmp_path):
    binary(tmp_path, 'frpc.exe')
    binary(tmp_path, 'cloudflared.exe')
    assert scan('frpc', [tmp_path], max_entries=1).incomplete


def test_cancel(tmp_path):
    from threading import Event
    cancel = Event()
    cancel.set()
    assert scan('frpc', [tmp_path], cancel=cancel).incomplete


def test_directory_links_not_followed(tmp_path):
    binary(tmp_path, 'outside/frpc.exe')
    (tmp_path / 'bin').mkdir()
    try:
        (tmp_path / 'bin/link').symlink_to(tmp_path / 'outside', target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation not permitted')
    assert not scan('frpc', [tmp_path]).candidates


def test_portable_selection_moves_with_config(tmp_path):
    root = tmp_path / 'original'
    expected = binary(root, 'bin/frp/v1/frpc.exe')
    settings = DesktopSettings(root / 'lan_config.toml')
    value = settings.program_value(expected)
    assert value == 'bin/frp/v1/frpc.exe'
    settings.save({'frpc_executable': value})
    moved = tmp_path / 'moved'
    root.rename(moved)
    after = DesktopSettings(moved / 'lan_config.toml')
    assert after.resolve(after.load()['frpc_executable']).is_file()
    outside = binary(tmp_path, 'external/frpc.exe')
    assert Path(after.program_value(outside)) == outside
