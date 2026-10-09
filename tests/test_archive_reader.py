import stat
import struct
import zipfile

import pytest

from lan_codex_share.archive_reader import ArchiveError, inspect_archive, read_member


def make_zip(tmp_path, entries):
    path = tmp_path / 'sample.zip'
    with zipfile.ZipFile(path, 'w') as z:
        for name, content in entries:
            z.writestr(name, content)
    return path


def test_member_bytes_directory_and_paging(tmp_path):
    path = make_zip(tmp_path, [('企业/说明.md', '# hello'), ('空/', '')] +
                    [(f'{i:03}.txt', 'x') for i in range(102)])
    listing = inspect_archive(str(path))
    assert listing['total'] == 104 and len(listing['entries']) == 100
    assert listing['entries'][0]['directory']
    assert len(inspect_archive(str(path), listing['version'], page=1)['entries']) == 4
    child = inspect_archive(str(path), listing['version'], '企业/')
    result = read_member(str(path), listing['version'], child['entries'][0]['id'])
    assert result['data'] == b'# hello'
    assert inspect_archive(str(path), listing['version'], '空/')['entries'] == []


@pytest.mark.parametrize('name', ['../secret', 'a/../secret', '/etc/x', 'C:/x', r'\\server\x',
                                  r'a\..\x', 'x\x00bad'])
def test_unsafe_names(tmp_path, name):
    path = make_zip(tmp_path, [(name, 'x')])
    # ZipFile truncates NULs while writing, so inject one into both name headers.
    if '\x00' in name:
        path = make_zip(tmp_path, [('xZbad', 'x')])
        path.write_bytes(path.read_bytes().replace(b'xZbad', b'x\x00bad'))
    with pytest.raises(ArchiveError):
        inspect_archive(str(path))


def test_duplicate_special_and_conflicting_members(tmp_path):
    for entries in [[('a/x', 'x'), (r'a\x', 'y')], [('a', 'x'), ('a/b', 'y')]]:
        with pytest.raises(ArchiveError):
            inspect_archive(str(make_zip(tmp_path, entries)))
    link = zipfile.ZipInfo('link')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ArchiveError):
        inspect_archive(str(make_zip(tmp_path, [(link, 'target')])))


def test_changed_version_and_invalid_index(tmp_path):
    path = make_zip(tmp_path, [('a', 'original')])
    version = inspect_archive(str(path))['version']
    for index in (-1, 5):
        with pytest.raises(ArchiveError):
            read_member(str(path), version, index)
    make_zip(tmp_path, [('b', 'replacement')])
    with pytest.raises(ArchiveError) as exc:
        read_member(str(path), version, 0)
    assert exc.value.status == 409


def test_damage_limits_encryption_crc(tmp_path, monkeypatch):
    from lan_codex_share import archive_reader as reader
    path = make_zip(tmp_path, [('a', 'unique payload')])
    original = path.read_bytes()
    path.write_bytes(original.replace(b'unique payload', b'broken payload'))
    version = inspect_archive(str(path))['version']
    with pytest.raises(ArchiveError):
        read_member(str(path), version, 0)
    raw = bytearray(original)
    central = raw.index(b'PK\x01\x02')
    struct.pack_into('<H', raw, central + 8, 1)
    path.write_bytes(raw)
    with pytest.raises(ArchiveError):
        inspect_archive(str(path))
    path.write_bytes(original)
    monkeypatch.setattr(reader, 'MAX_CENTRAL_BYTES', 2)
    with pytest.raises(ArchiveError) as exc:
        inspect_archive(str(path))
    assert exc.value.status == 413


def test_ratio_and_count_limits(tmp_path, monkeypatch):
    from lan_codex_share import archive_reader as reader
    path = tmp_path / 'sample.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('bomb', b'0' * 100_000)
    with pytest.raises(ArchiveError):
        inspect_archive(str(path))
    make_zip(tmp_path, [('a', 'x'), ('b', 'y')])
    monkeypatch.setattr(reader, 'MAX_ENTRIES', 1)
    with pytest.raises(ArchiveError):
        inspect_archive(str(path))
