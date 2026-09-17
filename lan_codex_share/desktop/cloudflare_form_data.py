"""Conservative scalar-only YAML edits for the local Cloudflare form."""
import json
import re
from urllib.parse import urlsplit

import yaml

from .config import UniqueLoader


def _parse(text):
    try:
        data = yaml.load(text, Loader=UniqueLoader)
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        if not isinstance(data, dict) or not isinstance(root, yaml.MappingNode):
            raise ValueError()
        anchored = any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for t in yaml.scan(text))
    except (yaml.YAMLError, ValueError, TypeError):
        raise ValueError('YAML 格式不适合表单，请在高级文件编辑中检查格式和重复字段') from None
    if anchored:
        raise ValueError('YAML 含锚点或别名，请使用高级文件编辑，避免改变其他引用')
    return data, root


def form_data(text):
    data, _ = _parse(text)
    for key in ('tunnel', 'credentials-file'):
        if key in data and not isinstance(data[key], str):
            raise ValueError('Tunnel 和凭证路径需为文本，请使用高级文件编辑调整')
    ingress = data.get('ingress', [])
    if not isinstance(ingress, list):
        raise ValueError('ingress 必须为规则数组，请使用高级文件编辑')
    rules = [(i, rule) for i, rule in enumerate(ingress)
             if isinstance(rule, dict) and isinstance(rule.get('hostname'), str)
             and isinstance(rule.get('service'), str) and rule['service'].startswith(('http://', 'https://'))]
    if not rules:
        raise ValueError('没有可编辑的 HTTP(S) 域名入口，请使用高级文件编辑或创建示例')
    return data, rules


def validate_field(key, value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\r\n\x00'):
        raise ValueError('请输入非空的单行文本')
    if key == 'hostname':
        try:
            host = value[2:] if value.startswith('*.') else value
            labels = host.encode('idna').decode('ascii').split('.')
            if len(host) > 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in labels):
                raise ValueError()
        except (UnicodeError, ValueError):
            raise ValueError('公网域名只能填写域名，不带协议、端口或路径') from None
    elif key == 'service':
        try:
            url = urlsplit(value)
            if (url.scheme not in ('http', 'https') or not url.hostname or
                    url.username is not None or url.password is not None or url.query or url.fragment or
                    any(c.isspace() for c in value) or (url.port is not None and not 1 <= url.port <= 65535)):
                raise ValueError()
        except ValueError:
            raise ValueError('回源地址需为有效 HTTP(S) 地址，不带认证、查询或片段') from None


def update_fields(text, updates, rule_index):
    if not updates:
        return text
    data, rules = form_data(text)
    if rule_index not in {index for index, _ in rules}:
        raise ValueError('所选入口已变化，请重新载入表单')
    _, root = _parse(text)
    top = {key.value: value for key, value in root.value}
    rule = top['ingress'].value[rule_index]
    nodes = {key.value: value for key, value in rule.value}
    edits, additions = [], []
    for key, value in updates.items():
        if key not in ('tunnel', 'credentials-file', 'hostname', 'service'):
            raise ValueError('表单不支持修改此字段')
        validate_field(key, value)
        current = data.get(key) if key in ('tunnel', 'credentials-file') else data['ingress'][rule_index].get(key)
        if value == current:
            continue
        node = (top if key in ('tunnel', 'credentials-file') else nodes).get(key)
        encoded = json.dumps(value, ensure_ascii=False)
        if node is None:
            if root.flow_style or key not in ('tunnel', 'credentials-file'):
                raise ValueError('该结构需在高级文件编辑中新增字段')
            additions.append(f'{key}: {encoded}')
        else:
            if not isinstance(node, yaml.ScalarNode) or node.style in ('|', '>'):
                raise ValueError('多行或复杂字段请使用高级文件编辑，原输入已保留')
            edits.append((node.start_mark.index, node.end_mark.index, encoded))
    if additions:
        newline = '\r\n' if '\r\n' in text else '\n'
        edits.append((root.start_mark.index, root.start_mark.index, newline.join(additions) + newline))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    form_data(text)
    return text
