"""Derive Share-targeted origins; never infer arbitrary TCP services as HTTP."""
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit

import tomlkit

from ..lan_access import normalize_public_origin
from ..lan_config import load_lan_config
from .config import ConfigDocument, _digest


def _port(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


def _loopback(value):
    return isinstance(value, str) and value.lower() in ('127.0.0.1', 'localhost', '::1')


def _candidates(kind, data, port, mode):
    found = set()
    if kind == 'frp':
        try:
            address = ip_address(data.get('serverAddr', ''))
            if address.version != 4:
                raise ValueError()
        except ValueError:
            return (), '自动同步仅支持现有 HTTP IPv4 公网入口；域名或公网 IPv6 请检查支持范围'
        for proxy in data.get('proxies', []):
            if (not isinstance(proxy, dict) or proxy.get('type') != 'tcp' or 'plugin' in proxy or
                    not _loopback(proxy.get('localIP')) or not _port(proxy.get('localPort')) or
                    proxy['localPort'] != port or not _port(proxy.get('remotePort'))):
                continue
            found.add(normalize_public_origin(f'http://{address}:{proxy["remotePort"]}'))
    else:
        if mode != 'yaml':
            return (), 'Token 模式不能推导域名，请在 Share 配置手动填写 cloudflare_origin'
        for rule in data.get('ingress', []):
            if not isinstance(rule, dict) or rule.get('path'):
                continue
            hostname, service = rule.get('hostname'), rule.get('service')
            if not isinstance(hostname, str) or not isinstance(service, str):
                continue
            try:
                upstream = urlsplit(service)
                if (upstream.scheme != 'http' or not _loopback(upstream.hostname) or
                        (upstream.port if upstream.port is not None else 80) != port or
                        upstream.username is not None or upstream.password is not None or
                        upstream.path not in ('', '/') or upstream.query or upstream.fragment or
                        any(c.isspace() for c in service)):
                    continue
                try:
                    ip_address(hostname)
                except ValueError:
                    pass
                else:
                    continue
                origin = normalize_public_origin('https://' + hostname)
                if urlsplit(origin).hostname != hostname.lower():
                    continue
                found.add(origin)
            except ValueError:
                continue
    if len(found) > 50:
        return (), '匹配入口过多，请在 Share 配置手动选择公网入口'
    return tuple(sorted(found)), '未找到明确回源当前 Share 的规则，请手动填写公网入口' if not found else ''


@dataclass
class SyncProposal:
    document: ConfigDocument = field(repr=False)
    text: str = field(repr=False)
    field: str
    current: str
    candidates: tuple[str, ...]
    reason: str = ''

    @property
    def needs_choice(self):
        return len(self.candidates) > 1 or bool(self.current and self.candidates and self.current != self.candidates[0])

    def apply(self, origin):
        if origin not in self.candidates:
            raise ValueError('所选入口不在当前候选中，请重新保存配置')
        if _digest(self.document.path) != self.document.digest:
            raise ValueError('Share 配置已被外部修改，请重新保存并确认')
        data = self.document.parse(self.text)
        if origin.startswith('http://') and not str(data.get('password', '')).strip():
            raise ValueError('HTTP 公网入口需要先设置非空项目密码')
        if origin == self.current and 'public_origin' not in data:
            return False
        if 'public_origin' in data:
            legacy = normalize_public_origin(data.pop('public_origin'))
            if legacy:
                key = 'cloudflare_origin' if legacy.startswith('https://') else 'frp_origin'
                data[key] = legacy
        data[self.field] = origin
        updated = tomlkit.dumps(data)
        if updated == self.text:
            return False
        self.document.save(updated)
        return True


def prepare_sync(lan_path, kind, data, mode='yaml'):
    if kind not in ('frp', 'cf'):
        raise ValueError('仅隧道配置支持入口同步')
    document = ConfigDocument(lan_path, 'lan')
    text = document.load()
    try:
        config = load_lan_config(lan_path)
    except (OSError, ValueError):
        raise ValueError('Share 配置不可用，请检查配置、项目目录及公网入口设置') from None
    target = 'frp_origin' if kind == 'frp' else 'cloudflare_origin'
    current = getattr(config, target)
    legacy_target = 'cloudflare_origin' if config.public_origin.startswith('https://') else 'frp_origin'
    if config.public_origin and legacy_target == target:
        current = config.public_origin
    candidates, reason = _candidates(kind, data, config.port, mode)
    return SyncProposal(document, text, target, current, candidates, reason)
