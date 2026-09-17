from __future__ import annotations

from ipaddress import ip_address, ip_network
import re
from urllib.parse import urlsplit


class AccessDenied(ValueError):
    pass


def normalize_public_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("public_origin 必须是 HTTPS 域名或 HTTP IPv4 地址字符串")
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
        parsed.scheme not in {"https", "http"}
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
        raise ValueError("public_origin 必须是完整 HTTPS 域名或 HTTP IPv4 地址，不能带路径、查询参数或凭据")
    if parsed.scheme == "http":
        try:
            address = ip_address(hostname)
            if address.version != 4 or str(address) != hostname:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("HTTP public_origin 只支持规范 IPv4 地址，可附加公网端口") from exc
    default_port = 443 if parsed.scheme == "https" else 80
    return f"{parsed.scheme}://{hostname}" + (f":{port}" if port not in {None, default_port} else "")


PRIVATE_V4 = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def origin_authorities(origin: str) -> set[str]:
    parsed = urlsplit(origin)
    authorities = {parsed.netloc}
    if parsed.port is None:
        authorities.add(f"{parsed.hostname}:{443 if parsed.scheme == 'https' else 80}")
    return authorities


def normalize_entry_origins(public_origin: str = "", cloudflare_origin: str = "", frp_origin: str = "") -> tuple[str, ...]:
    legacy, cloudflare, frp = (normalize_public_origin(value) for value in (public_origin, cloudflare_origin, frp_origin))
    if legacy and (cloudflare or frp):
        raise ValueError("public_origin 不能与 cloudflare_origin/frp_origin 混用，请删除旧字段")
    if cloudflare and not cloudflare.startswith("https://"):
        raise ValueError("cloudflare_origin 必须使用 HTTPS")
    entries = tuple(dict.fromkeys(value for value in (legacy, cloudflare, frp) if value))
    authorities: dict[str, str] = {}
    for entry in entries:
        for authority in origin_authorities(entry):
            if authority in authorities and authorities[authority] != entry:
                raise ValueError("公网入口的 Host 与端口相同但协议不同，无法区分回源，请使用不同地址或端口")
            authorities[authority] = entry
    return entries


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


def request_origin(host: str, allowed_hosts: set[str], public_origin: str | tuple[str, ...] = "") -> str:
    entries = (public_origin,) if isinstance(public_origin, str) and public_origin else public_origin
    matched_hostname = False
    for entry in entries:
        if host_name(host) == urlsplit(entry).hostname:
            matched_hostname = True
            if host.lower() in origin_authorities(entry):
                return entry
    if matched_hostname:
        raise AccessDenied("公网 Host 端口不允许")
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
    public_origin: str | tuple[str, ...] = "",
) -> None:
    expected_origin = request_origin(host, allowed_hosts, public_origin)
    if origin.rstrip("/") != expected_origin.rstrip("/"):
        raise AccessDenied("Origin 不允许")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise AccessDenied("Content-Type 必须是 application/json")
    if not csrf or csrf != expected_csrf:
        raise AccessDenied("CSRF 校验失败")
