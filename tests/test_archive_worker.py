import pytest
from lan_codex_share.archive_reader import ArchiveError
from lan_codex_share.archive_worker import run_archive, _SLOTS
from tests.test_archive_reader import make_zip


def test_isolated_roundtrip(tmp_path):
    path = make_zip(tmp_path, [('a.txt', 'hello')])
    listing = run_archive(str(path), 'list')
    args = {'version': listing['version'], 'member': 0}
    assert run_archive(str(path), 'download', **args)['data'] == b'hello'
    assert run_archive(str(path), 'preview', **args)['content'] == 'hello'


def test_busy_and_timeout_release_slots(tmp_path):
    path = make_zip(tmp_path, [('a', 'x')])
    _SLOTS.acquire()
    _SLOTS.acquire()
    try:
        with pytest.raises(ArchiveError) as exc:
            run_archive(str(path), 'list')
        assert exc.value.status == 429
    finally:
        _SLOTS.release()
        _SLOTS.release()
    with pytest.raises(ArchiveError) as exc:
        run_archive(str(path), 'list', timeout=0)
    assert exc.value.status == 408
    assert run_archive(str(path), 'list')['entries']
