"""Bounded ZIP access. Member names are labels, never extraction paths."""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import stat
import struct
import unicodedata
import zipfile

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_CENTRAL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_MEMBER_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024


class ArchiveError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def safe_name(raw):
    name = unicodedata.normalize('NFC', raw.replace('\\', '/'))
    parts = name.rstrip('/').split('/')
    if (not name or name.startswith('/') or ':' in name or '\x00' in raw
            or len(parts) > 32 or any(p in {'', '.', '..'} for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ArchiveError('ZIP 含不安全的成员路径')
    return name


def _stamp(stream):
    value = os.fstat(stream.fileno())
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _central(stream, size):
    if size > MAX_ARCHIVE_BYTES:
        raise ArchiveError('ZIP 超过 200 MiB 浏览上限，请下载整包', 413)
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail) - offset < 22:
        raise ArchiveError('ZIP 损坏或不是有效的 ZIP 文件')
    _, disk, central_disk, count_disk, count, length, start, comment = struct.unpack_from('<4s4H2IH', tail, offset)
    if disk or central_disk or count_disk != count or count == 65535 or length == 0xffffffff or start == 0xffffffff:
        raise ArchiveError('暂不支持分卷或 ZIP64 浏览，请下载整包')
    if count > MAX_ENTRIES or length > MAX_CENTRAL_BYTES:
        raise ArchiveError('ZIP 条目数或中央目录大小超限，请下载整包', 413)
    if offset + 22 + comment != len(tail) or start + length != size - len(tail) + offset:
        raise ArchiveError('ZIP 目录结构无效')
    stream.seek(start)
    central = stream.read(length)
    # Validate the *actual* count before ZipFile allocates the directory objects.
    cursor = actual = 0
    while cursor < len(central):
        if central[cursor:cursor + 4] != b'PK\x01\x02' or len(central) - cursor < 46:
            raise ArchiveError('ZIP 中央目录损坏')
        a, b, c = struct.unpack_from('<HHH', central, cursor + 28)
        cursor += 46 + a + b + c
        actual += 1
        if actual > MAX_ENTRIES:
            raise ArchiveError('ZIP 条目数超限', 413)
    if actual != count or cursor != length:
        raise ArchiveError('ZIP 目录计数不一致')
    return central


def _validate_entries(entries):
    names, files, explicit, directories = [], set(), set(), set()
    total = 0
    for entry in entries:
        name = safe_name(entry.orig_filename)
        key = name.rstrip('/')
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ArchiveError('ZIP 含软链接或特殊文件，不能浏览')
        if key in explicit:
            raise ArchiveError('ZIP 含重复或冲突的成员名称')
        explicit.add(key)
        if entry.flag_bits & 1:
            raise ArchiveError('暂不支持加密 ZIP，请下载整包')
        if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            raise ArchiveError('ZIP 使用不支持的压缩算法')
        if entry.file_size > MAX_MEMBER_BYTES or entry.file_size > max(1, entry.compress_size) * 100:
            raise ArchiveError('ZIP 成员大小或压缩比超限，请下载整包', 413)
        total += entry.file_size
        if total > MAX_TOTAL_BYTES:
            raise ArchiveError('ZIP 总解压大小超限，请下载整包', 413)
        if name.endswith('/'):
            directories.add(key)
        else:
            if mode == stat.S_IFDIR:
                raise ArchiveError('ZIP 文件类型和路径不一致')
            files.add(key)
        parts = key.split('/')
        directories.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        names.append(name)
    if files & directories:
        raise ArchiveError('ZIP 含文件和目录名称冲突')
    return names, directories


@contextmanager
def checked_archive(path, version=''):
    try:
        with Path(path).open('rb') as stream:
            before = _stamp(stream)
            central = _central(stream, before[2])
            token = sha256(repr(before).encode() + central).hexdigest()
            if version and version != token:
                raise ArchiveError('压缩包已修改，请刷新后重试', 409)
            with zipfile.ZipFile(stream) as archive:
                names, directories = _validate_entries(archive.infolist())
                yield archive, token, names, directories
            if _stamp(stream) != before or Path(path).stat().st_ino != before[1]:
                raise ArchiveError('压缩包已修改，请刷新后重试', 409)
    except ArchiveError:
        raise
    except FileNotFoundError as exc:
        raise ArchiveError('压缩包不存在', 404) from exc
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError, EOFError) as exc:
        raise ArchiveError('ZIP 损坏、无法读取或压缩格式不受支持') from exc


def inspect_archive(path: str, version: str = '', directory: str = '', page: int = 0) -> dict:
    if not isinstance(page, int) or not 0 <= page < MAX_ENTRIES:
        raise ArchiveError('目录页码无效')
    directory = safe_name(directory).rstrip('/') + '/' if directory else ''
    with checked_archive(path, version) as (archive, token, names, directories):
        if directory and directory.rstrip('/') not in directories:
            raise ArchiveError('ZIP 目录不存在', 404)
        children = {}
        for index, name in enumerate(names):
            if not name.startswith(directory) or name == directory:
                continue
            rest = name[len(directory):]
            first = rest.split('/')[0]
            is_dir = '/' in rest
            children[first] = {'id': None if is_dir else index, 'name': first,
                'path': directory + first + ('/' if is_dir else ''), 'directory': is_dir,
                'size': 0 if is_dir else archive.infolist()[index].file_size}
        entries = sorted(children.values(), key=lambda e: (not e['directory'], e['name'].casefold()))
        return {'version': token, 'directory': directory, 'page': page, 'total': len(entries),
                'entries': entries[page * 100:(page + 1) * 100]}


def read_member(path: str, version: str, member: int) -> dict:
    if not version:
        raise ArchiveError('缺少压缩包版本，请重新打开')
    with checked_archive(path, version) as (archive, _, names, _):
        if not isinstance(member, int) or not 0 <= member < len(names):
            raise ArchiveError('ZIP 成员索引无效', 404)
        entry = archive.infolist()[member]
        if names[member].endswith('/'):
            raise ArchiveError('目录不能作为文件下载')
        with archive.open(entry) as stream:
            chunks, count = [], 0
            while True:
                chunk = stream.read(min(256 * 1024, MAX_MEMBER_BYTES - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_MEMBER_BYTES or count > entry.file_size:
                    raise ArchiveError('ZIP 成员实际大小与声明不符或超限', 413)
                chunks.append(chunk)
            if count != entry.file_size:
                raise ArchiveError('ZIP 成员实际大小与声明不符或超限', 413)
            data = b''.join(chunks)
        return {'name': names[member].split('/')[-1], 'size': len(data), 'data': data}
