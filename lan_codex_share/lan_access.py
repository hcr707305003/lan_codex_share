from __future__ import annotations

from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit


class AccessDenied(ValueError):
    pass


PRIVATE_V4 = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def is_lan_client(value: str) -> bool:
    try:
        address = ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if address.version == 4:
        return any(address in network for network in PRIVATE_V4)
    return address.is_link_local or address.is_private


def host_name(host_header: str) -> str:
    try:
        return (urlsplit(f"//{host_header}").hostname or "").lower()
    except ValueError:
        return ""


def validate_host(host: str, allowed_hosts: set[str]) -> None:
    if host_name(host) not in {item.lower() for item in allowed_hosts}:
        raise AccessDenied("Host 不允许")


def validate_mutating_request(
    *,
    host: str,
    origin: str,
    content_type: str,
    csrf: str,
    expected_csrf: str,
    allowed_hosts: set[str],
) -> None:
    validate_host(host, allowed_hosts)
    if origin.rstrip("/") != f"http://{host}".rstrip("/"):
        raise AccessDenied("Origin 不允许")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise AccessDenied("Content-Type 必须是 application/json")
    if not csrf or csrf != expected_csrf:
        raise AccessDenied("CSRF 校验失败")
