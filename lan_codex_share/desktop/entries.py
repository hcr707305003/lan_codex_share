"""Display metadata from configuration, not a claim of live connectivity."""
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..lan_config import load_lan_config
from .config import ConfigDocument


@dataclass(frozen=True)
class EntryInfo:
    text: str
    url: str = ''
    detail: str = ''


def safe_web_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return ''
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username is not None or parsed.password is not None):
            return ''
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return ''
        return value
    except ValueError:
        return ''


def service_entries(config_path, settings):
    entries = {'Share': EntryInfo('LAN 配置不可用'),
               'frpc': EntryInfo('FRP 配置不可用'),
               'Tunnel': EntryInfo('请配置 Cloudflare 公网入口')}
    try:
        config = load_lan_config(config_path)
        entries['Share'] = EntryInfo(f'本地监听端口：{config.port}', f'http://localhost:{config.port}',
                                     '配置值；运行中的服务可能需要重启后生效')
        cf, frp = config.cloudflare_origin, config.frp_origin
        legacy = config.public_origin
        if legacy:
            if legacy.startswith('https://'):
                cf = legacy
            else:
                frp = legacy
        entries['Tunnel'] = EntryInfo(f'Share 回源参考端口：{config.port}', safe_web_url(cf),
                                     ('旧配置 public_origin；' if legacy and cf else '') +
                                     '实际回源以 Cloudflare Tunnel 配置为准；公网连接未验证')
        entries['frpc'] = EntryInfo('FRP 配置未读取', safe_web_url(frp),
                                   ('旧配置 public_origin；' if legacy and frp else '') + '公网连接未验证')
    except (OSError, ValueError):
        pass
    try:
        path = settings.resolve(settings.load()['frpc_config'])
        if path.stat().st_size > 256 * 1024:
            raise ValueError('oversized config')
        data = ConfigDocument(path, 'frp').validate(path.read_text(encoding='utf-8-sig'))
        rows = [f'{p["localPort"]} → {p["remotePort"]}' for p in data.get('proxies', [])
                if p.get('type') == 'tcp' and 'localPort' in p and 'remotePort' in p]
        text = f'服务端控制端口：{data.get("serverPort", 7000)}\n本地 → 公网业务端口：'
        text += '\n' + (' / '.join(rows[:2]) if rows else '未配置 TCP 端口映射')
        if len(rows) > 2:
            text += f'\n共 {len(rows)} 条映射，悬停查看'
        previous = entries['frpc']
        detail = previous.detail + '\n本地 → 公网业务端口\n' + '\n'.join(rows[:20])
        if len(rows) > 20:
            detail += '\n更多映射请查看配置'
        entries['frpc'] = EntryInfo(text, previous.url, detail)
    except (OSError, ValueError, TypeError, KeyError):
        previous = entries['frpc']
        entries['frpc'] = EntryInfo('FRP 配置缺失或不可用', previous.url, previous.detail)
    return entries
