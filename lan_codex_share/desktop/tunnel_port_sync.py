"""Synchronize known Share upstreams without changing unrelated tunnel rules."""
from dataclasses import dataclass, field
import json
from urllib.parse import urlsplit, urlunsplit

import tomlkit
import yaml

from .config import ConfigDocument, _port
from .origin_sync import _loopback


@dataclass
class PortSyncProposal:
    document: ConfigDocument = field(repr=False)
    text: str = field(repr=False)
    count: int

    def apply(self):
        self.document.save(self.text)
        return self.count


def _service_url(value, old_port, new_port):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'http' or not _loopback(url.hostname) or
                (url.port if url.port is not None else 80) != old_port or
                url.username is not None or url.password is not None or url.query or url.fragment):
            return None
        host = url.netloc.rsplit(':', 1)[0] if url.port is not None else url.netloc.removesuffix(':')
        return urlunsplit((url.scheme, f'{host}:{new_port}', url.path, '', ''))
    except ValueError:
        return None


def _update_yaml(text, old_port, new_port):
    # Aliases can share nodes with unrelated settings. Do not mutate them implicitly.
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError('YAML 含锚点或别名，请手动检查回源端口')
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    replacements = []
    for key, rules in root.value:
        if key.value != 'ingress' or not isinstance(rules, yaml.SequenceNode):
            continue
        for rule in rules.value:
            if not isinstance(rule, yaml.MappingNode):
                continue
            for name, value in rule.value:
                if name.value != 'service' or not isinstance(value, yaml.ScalarNode):
                    continue
                updated = _service_url(value.value, old_port, new_port)
                if updated is not None:
                    # Block scalars own their final newline; retain it for the next YAML key.
                    ending = ''
                    if value.style in ('|', '>'):
                        segment = text[value.start_mark.index:value.end_mark.index]
                        ending = '\r\n' if segment.endswith('\r\n') else '\n' if segment.endswith('\n') else ''
                    replacements.append((value.start_mark.index, value.end_mark.index,
                                         json.dumps(updated, ensure_ascii=False) + ending))
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text, len(replacements)


def prepare_port_sync(path, kind, old_port, new_port):
    if kind not in ('frp', 'cf'):
        raise ValueError('不支持的隧道配置类型')
    _port(old_port, '原 Share 端口')
    _port(new_port, '新 Share 端口')
    document = ConfigDocument(path, kind)
    text = document.load()
    data = document.validate(text)
    count = 0
    if kind == 'frp':
        for proxy in data.get('proxies', []):
            if (proxy.get('type') == 'tcp' and 'plugin' not in proxy and
                    _loopback(proxy.get('localIP')) and proxy.get('localPort') == old_port):
                proxy['localPort'] = new_port
                count += 1
        updated = tomlkit.dumps(data)
    else:
        updated, count = _update_yaml(text, old_port, new_port)
    if not count:
        raise ValueError('未找到明确指向原 Share 端口的本地回源规则，请手动检查')
    document.validate(updated)
    return PortSyncProposal(document, updated, count)
