"""Bounded, best-effort URL adaptation for trusted apps mounted below /proxy/."""

from html import escape
from html.parser import HTMLParser
from http.cookies import CookieError, SimpleCookie
from ipaddress import ip_address
import json
import re
from urllib.parse import urlsplit

from .lan_access import PRIVATE_V4


def local_authority(parsed) -> str | None:
    """Classify without DNS; actual access/blocked-port checks remain in the proxy."""
    if parsed.scheme not in {"", "http", "ws"}:
        return None
    match = re.fullmatch(r"(localhost|\d+\.\d+\.\d+\.\d+|\[::1\])(?::([1-9]\d{0,4}))?", parsed.netloc, re.I)
    if not match:
        return None
    name, port = match[1].lower(), int(match[2] or 80)
    if port > 65535:
        return None
    try:
        address = ip_address("127.0.0.1" if name == "localhost" else name.strip("[]"))
    except ValueError:
        return None
    if address.is_loopback or (address.version == 4 and any(address in network for network in PRIVATE_V4)):
        return f"{name}:{port}"
    return None


def rewrite_url(value: str, prefix: str, authority: str) -> str:
    if value.startswith("/proxy/"):
        return value
    if value.startswith("/") and not value.startswith("//"):
        return prefix.rstrip("/") + value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    target = local_authority(parsed)
    if target is not None:
        result = "/proxy/" + target + (parsed.path or "/")
        if parsed.query:
            result += "?" + parsed.query
        if parsed.fragment:
            result += "#" + parsed.fragment
        return result
    return value


def rewrite_css(text: str, prefix: str, authority: str) -> str:
    text = re.sub(r"(url\(\s*)([\"']?)([^\s)\"']+)([\"']?\s*\))",
                  lambda m: m[1] + m[2] + rewrite_url(m[3], prefix, authority) + m[4], text, flags=re.I)
    return re.sub(r"(@import\s+)([\"'])([^\"']+)([\"'])",
                  lambda m: m[1] + m[2] + rewrite_url(m[3], prefix, authority) + m[4], text, flags=re.I)


def rewrite_json(data: bytes, content_type: str, prefix: str, authority: str, origin: str) -> bytes | None:
    """Repair same-backend URLs without reserializing numbers or business data."""
    charset = re.search(r"charset\s*=\s*[\"']?([^\s;\"']+)", content_type, re.I)
    encoding = charset[1] if charset else "utf-8"
    try:
        text = data.decode(encoding)
        # Validate structure, but keep original numeric tokens and formatting.
        json.loads(text, parse_int=str, parse_float=str)
        changed = False

        def replace(match):
            nonlocal changed
            if match[1]:  # Object key, not a resource value.
                return match[0]
            value = json.loads(match[0])
            if not re.match(r"^https?://", value, re.I) or any(char.isspace() or ord(char) < 32 for char in value):
                return match[0]
            try:
                parsed = urlsplit(value)
            except ValueError:
                return match[0]
            if parsed.netloc.lower() != authority.lower():
                return match[0]
            # The response came from this exact HTTP backend. It may synthesize
            # HTTPS URLs from forwarded protocol + internal Host (e.g. QR APIs).
            tail = value.split("://", 1)[1][len(parsed.netloc):]
            mapped = origin.rstrip("/") + prefix.rstrip("/") + (tail if tail.startswith("/") else "/" + tail)
            changed = True
            return json.dumps(mapped, ensure_ascii=True)

        result = re.sub(r'"(?:[^"\\]|\\.)*"(\s*:)?', replace, text)
        return result.encode(encoding) if changed else None
    except (LookupError, UnicodeError, ValueError, RecursionError):
        return None


class ProxyHTML(HTMLParser):
    def __init__(self, prefix: str, authority: str):
        super().__init__(convert_charrefs=False)
        self.prefix = prefix
        self.authority = authority
        self.parts: list[str] = []
        self.injected = False
        self.in_style = False

    def inject(self):
        if not self.injected:
            self.parts.append(
                '<script src="/proxy-client.js" data-prefix="' + escape(self.prefix, quote=True)
                + '" data-upstream="http://' + escape(self.authority, quote=True) + '"></script>'
            )
            self.injected = True

    def handle_starttag(self, tag, attrs):
        if tag not in {"html", "head"}:
            self.inject()
        adapted = []
        for key, value in attrs:
            if value is not None:
                if key in {"href", "src", "action", "formaction", "poster", "data"}:
                    value = rewrite_url(value, self.prefix, self.authority)
                elif key == "style":
                    value = rewrite_css(value, self.prefix, self.authority)
                elif key == "srcset" and "data:" not in value:
                    value = ", ".join(
                        " ".join([rewrite_url(bits[0], self.prefix, self.authority), *bits[1:]])
                        for entry in value.split(",") if (bits := entry.split())
                    )
            adapted.append(" " + key + ("" if value is None else '="' + escape(value, quote=True) + '"'))
        self.parts.append("<" + tag + "".join(adapted) + ">")
        if tag == "head":
            self.inject()
        self.in_style = tag == "style" or self.in_style

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        self.parts.append(rewrite_css(data, self.prefix, self.authority) if self.in_style else data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def handle_pi(self, data):
        self.parts.append(f"<?{data}>")


def rewrite_document(data: bytes, content_type: str, prefix: str, authority: str) -> bytes | None:
    charset = re.search(r"charset\s*=\s*[\"']?([^\s;\"']+)", content_type, re.I)
    encoding = charset[1] if charset else "utf-8"
    try:
        text = data.decode(encoding)
        if content_type.lower().startswith("text/html"):
            parser = ProxyHTML(prefix, authority)
            parser.feed(text)
            parser.close()
            text = "".join(parser.parts)
        else:
            text = rewrite_css(text, prefix, authority)
        return text.encode(encoding)
    except (LookupError, UnicodeError, ValueError):
        return None


def rewrite_cookie(value: str, prefix: str, upstream_path: str, auth_cookie: str) -> list[str]:
    cookie = SimpleCookie()
    try:
        cookie.load(value)
        result = []
        for name, morsel in cookie.items():
            if name == auth_cookie:
                continue
            path = morsel["path"]
            if not path.startswith("/"):
                path = upstream_path.rsplit("/", 1)[0] or "/"
            morsel["path"] = prefix.rstrip("/") + path
            morsel["domain"] = ""
            result.append(morsel.OutputString())
        return result
    except (CookieError, ValueError):
        return []
