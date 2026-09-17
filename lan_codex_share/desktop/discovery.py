"""Bounded, read-only component discovery. Never runs candidate programs."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import shutil
import stat
from threading import Event


@dataclass(frozen=True)
class Discovery:
    candidates: tuple[Path, ...] = ()
    incomplete: bool = False


def usable(path: Path, system: str | None = None) -> bool:
    try:
        return path.is_file() and ((system or platform.system()) == 'Windows' or os.access(path, os.X_OK))
    except OSError:
        return False


def discover(name, roots, *, system=None, machine=None, cancel=None, max_entries=4000):
    if name not in ('frpc', 'cloudflared'):
        raise ValueError('Unsupported component')
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    os_key = {'Windows': 'windows', 'Darwin': 'darwin', 'Linux': 'linux'}.get(system, '')
    arch = {'amd64': 'amd64', 'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64',
            'x86': '386', 'i386': '386', 'i686': '386'}.get(machine, machine)
    suffix = '.exe' if system == 'Windows' else ''
    names = {name + suffix}
    if os_key and arch:
        names.update({f'{name}-{os_key}-{arch}{suffix}', f'{name}_{os_key}_{arch}{suffix}'})
    cancel = cancel or Event()
    found, visited = set(), set()
    remaining = max_entries
    incomplete = False

    def visit(directory, depth, root=False):
        nonlocal remaining, incomplete
        if cancel.is_set():
            incomplete = True
            return
        try:
            # Do not traverse junctions/reparse points, including bin itself.
            info = directory.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return
            resolved = directory.resolve()
            if resolved in visited:
                return
            visited.add(resolved)
            with os.scandir(directory) as entries:
                for entry in entries:
                    if remaining <= 0 or cancel.is_set():
                        incomplete = True
                        return
                    remaining -= 1
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        filename = entry.name.lower() if system == 'Windows' else entry.name
                        if filename in names and usable(Path(entry.path), system):
                            found.add(Path(entry.path).resolve())
                    elif entry.is_dir(follow_symlinks=False):
                        if root:
                            if entry.name == 'bin':
                                visit(Path(entry.path), 3)
                        elif depth > 0:
                            tag = re.search(r'(windows|linux|darwin)[_-](amd64|arm64|386|arm\w*)', entry.name.lower())
                            if not tag or tag.groups() == (os_key, arch):
                                visit(Path(entry.path), depth - 1)
        except FileNotFoundError:
            pass
        except OSError:
            incomplete = True

    for root in dict.fromkeys(Path(p).absolute() for p in roots):
        visit(root, 0, root=True)
    if not found and not incomplete:
        path = shutil.which(name)
        if path and usable(Path(path), system):
            found.add(Path(path).resolve())
    return Discovery(tuple(sorted(found, key=lambda p: str(p).casefold())), incomplete)
