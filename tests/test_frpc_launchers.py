import os
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_frpc_example_maps_one_share_port():
    config = tomllib.loads((ROOT / 'frpc.example.toml').read_text(encoding='utf-8'))
    assert config['serverAddr'] == '192.0.2.10'
    assert config['serverPort'] == 7000
    assert config['auth']['token'] == 'REPLACE_WITH_YOUR_FRP_TOKEN'
    assert config['transport']['tls']['enable'] is True
    assert config['proxies'] == [{'name': 'lan-codex-share', 'type': 'tcp',
                                  'localIP': '127.0.0.1', 'localPort': 9000, 'remotePort': 20000}]


def shell_binary():
    if os.name == 'nt':
        git = shutil.which('git')
        candidate = Path(git).parent.parent / 'bin/sh.exe' if git else None
        if candidate and candidate.is_file():
            return str(candidate)
        pytest.skip('Git Bash required on Windows')
    return shutil.which('sh') or pytest.skip('POSIX sh required')


def test_frpc_shell_paths_and_exit_codes(tmp_path):
    shell = shell_binary()
    folder = tmp_path / 'script folder'
    folder.mkdir()
    script = folder / 'start_frpc.sh'
    shutil.copyfile(ROOT / script.name, script)
    binary = folder / 'frpc'
    binary.write_text('#!/bin/sh\nprintf "ARG:%s\\n" "$@"\nexit 7\n', encoding='utf-8', newline='\n')
    binary.chmod(0o755)
    missing = subprocess.run([shell, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert missing.returncode == 2 and 'Missing frpc config' in missing.stderr
    config = folder / 'frpc.toml'
    config.write_text('# test', encoding='utf-8')
    default = subprocess.run([shell, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert default.returncode == 7
    assert default.stdout.splitlines()[0] == 'ARG:-c'
    assert default.stdout.splitlines()[1].endswith('/script folder/frpc.toml')
    custom = tmp_path / 'custom config.toml'
    custom.write_text('# test', encoding='utf-8')
    selected = subprocess.run([shell, str(script), custom.name], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert selected.returncode == 7 and selected.stdout.splitlines() == ['ARG:-c', 'ARG:custom config.toml']


@pytest.mark.skipif(os.name != 'nt', reason='Windows cmd only')
def test_frpc_cmd_missing_config_is_noninteractive(tmp_path):
    script = tmp_path / 'start_frpc.cmd'
    shutil.copyfile(ROOT / script.name, script)
    result = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(script)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert result.returncode == 2 and 'Missing frpc config' in result.stdout
