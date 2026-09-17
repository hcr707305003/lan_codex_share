from lan_codex_share.desktop.logs import LogBuffer


def test_redaction_before_storage(tmp_path):
    log = LogBuffer(tmp_path)
    log.set_secrets(['my-secret'])
    log.add('frpc', 'auth.token=my-secret Authorization: Bearer abc Cookie: sid=123')
    text = '\n'.join(log.filtered())
    assert 'my-secret' not in text
    assert 'abc' not in text
    assert 'sid=123' not in text
    assert 'my-secret' not in (tmp_path / 'desktop.log').read_text()


def test_bounded_buffer_and_filter():
    log = LogBuffer(limit=2)
    log.add('Share', 'first')
    log.add('frpc', 'second')
    log.add('Share', 'third')
    assert log.dropped == 1
    assert len(log.filtered('frpc')) == 1
    assert len(log.filtered(query='third')) == 1


def test_multiline_secret_is_redacted_before_split():
    log = LogBuffer()
    log.set_secrets(['first\nsecond'])
    log.add('Share', 'value=first\nsecond')
    assert 'first' not in '\n'.join(log.filtered())
