from __future__ import annotations

from ipaddress import ip_address, ip_network
import re
from urllib.parse import urlsplit


class AccessDenied(ValueError):
    pass


def normalize_public_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("public_origin 必须是 HTTPS 地址字符串")
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ValueError("public_origin 地址无效") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or len(hostname) > 253
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in hostname.split("."))
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment
        or any(char.isspace() for char in value)
        or "?" in value or "#" in value or "\\" in value
        or parsed.netloc.endswith(":")
        or port == 0
    ):
        raise ValueError("public_origin 必须是完整 HTTPS 域名地址，不能带路径、查询参数或凭据")
    return f"https://{hostname}" + (f":{port}" if port not in {None, 443} else "")


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


def request_origin(host: str, allowed_hosts: set[str], public_origin: str = "") -> str:
    if public_origin:
        public = urlsplit(public_origin)
        if host_name(host) == public.hostname:
            authorities = {public.netloc}
            if public.port is None:
                authorities.add(f"{public.hostname}:443")
            if host.lower() not in authorities:
                raise AccessDenied("公网 Host 端口不允许")
            return public_origin
    validate_host(host, allowed_hosts)
    return f"http://{host}"


def validate_mutating_request(
    *,
    host: str,
    origin: str,
    content_type: str,
    csrf: str,
    expected_csrf: str,
    allowed_hosts: set[str],
    public_origin: str = "",
) -> None:
    expected_origin = request_origin(host, allowed_hosts, public_origin)
    if origin.rstrip("/") != expected_origin.rstrip("/"):
        raise AccessDenied("Origin 不允许")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise AccessDenied("Content-Type 必须是 application/json")
    if not csrf or csrf != expected_csrf:
        raise AccessDenied("CSRF 校验失败")
