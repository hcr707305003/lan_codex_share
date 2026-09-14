import pytest

from lan_codex_share.lan_access import AccessDenied, is_lan_client, validate_mutating_request


def test_public_origin_accepts_https_without_weakening_local_origin():
    values = dict(
        host="codex.example.com", origin="https://codex.example.com",
        content_type="application/json", csrf="secret", expected_csrf="secret",
        allowed_hosts={"localhost"}, public_origin="https://codex.example.com",
    )
    validate_mutating_request(**values)
    validate_mutating_request(**{**values, "host": "codex.example.com:443"})
    validate_mutating_request(**{**values, "host": "localhost:9000", "origin": "http://localhost:9000"})
    validate_mutating_request(**{**values, "host": "codex.example.com:8443", "origin": "https://codex.example.com:8443", "public_origin": "https://codex.example.com:8443"})
    for changes in (
        {"origin": "http://codex.example.com"},
        {"origin": "https://other.example.com"},
        {"origin": "https://codex.example.com.evil.example"},
        {"origin": "null"}, {"origin": ""}, {"csrf": "wrong"},
        {"host": "codex.example.com:9000"},
        {"host": "codex.example.com:0443"},
        {"host": "user@codex.example.com"},
        {"host": "codex.example.com/extra"},
        {"host": "localhost:9000"},
        {"host": "other.example.com"},
        {"public_origin": ""},
    ):
        with pytest.raises(AccessDenied):
            validate_mutating_request(**{**values, **changes})


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.8.9", "::1", "fe80::1", "fd00::1"],
)
def test_allow_local_addresses(address):
    assert is_lan_client(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "172.32.0.1", "1.1.1.1", "2001:4860:4860::8888", "not-an-ip"])
def test_reject_non_lan_addresses(address):
    assert not is_lan_client(address)


def test_validate_same_origin_mutation():
    validate_mutating_request(
        host="192.168.1.20:8765",
        origin="http://192.168.1.20:8765",
        content_type="application/json; charset=utf-8",
        csrf="secret",
        expected_csrf="secret",
        allowed_hosts={"192.168.1.20", "localhost"},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"host": "evil.example"},
        {"origin": "http://evil.example"},
        {"content_type": "text/plain"},
        {"csrf": "wrong"},
    ],
)
def test_reject_invalid_mutation(changes):
    values = {
        "host": "192.168.1.20:8765",
        "origin": "http://192.168.1.20:8765",
        "content_type": "application/json",
        "csrf": "secret",
        "expected_csrf": "secret",
        "allowed_hosts": {"192.168.1.20", "localhost"},
    }
    values.update(changes)
    with pytest.raises(AccessDenied):
        validate_mutating_request(**values)
