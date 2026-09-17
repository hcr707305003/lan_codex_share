"""Verify an assembled desktop archive without starting Share or any tunnel."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='lan-desktop-package-') as temporary:
        destination = Path(temporary)
        with zipfile.ZipFile(args.archive) as archive:
            for name in archive.namelist():
                if not (destination / name).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('archive path escapes test directory')
            archive.extractall(destination)
        root = destination / args.archive.stem
        suffix = '.exe' if os.name == 'nt' else ''
        desktop = root / f'lan_codex_desktop{suffix}'
        cli = root / f'lan_codex_share{suffix}'
        # Local Windows archive smoke; native-platform .app/ELF smoke runs in CI.
        assert desktop.is_file() and cli.is_file()
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        for arguments in ([str(desktop), '--smoke-test'],
                          [str(desktop), '--smoke-test', '--config', str(root / 'other-config' / 'lan_config.toml')]):
            result = subprocess.run(arguments, cwd=destination, env=env, timeout=20)
            assert result.returncode == 0, f'Desktop smoke failed: {result.returncode}'
        assert (root / 'runtime' / 'desktop' / 'desktop.log').is_file()
        assert (root / 'other-config' / 'runtime' / 'desktop' / 'desktop.log').is_file()
        for arguments in ([str(cli), '--version'], [str(cli), 'cli', '--help']):
            result = subprocess.run(arguments, capture_output=True, timeout=20)
            assert result.returncode == 0
        assert not list(root.rglob('startup-error.log'))
    print('Assembled GUI/CLI archive: startup, default config root and explicit config path PASS')


if __name__ == '__main__':
    main()
