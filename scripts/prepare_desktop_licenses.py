"""Collect upstream Qt license texts for the local build, never user data."""
from pathlib import Path
from urllib.request import urlopen


def main():
    destination = Path(__file__).resolve().parents[1] / 'build' / 'desktop-licenses'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('LGPL-3.0-only.txt', 'GPL-3.0-only.txt', 'GPL-2.0-only.txt'):
        url = f'https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/{name}'
        with urlopen(url, timeout=30) as response:
            payload = response.read(256 * 1024)
        if len(payload) < 1000:
            raise ValueError(f'Missing upstream license: {name}')
        (destination / name).write_bytes(payload)
    print('Qt license texts ready')


if __name__ == '__main__':
    main()
