"""Package-relative identity and original, themeable UI glyphs."""
from functools import lru_cache
from pathlib import Path
from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer


def asset_path(name):
    return Path(__file__).resolve().parent / 'assets' / name


def app_icon():
    return QIcon(str(asset_path('app-icon.svg')))


_PATHS = {
    'overview': '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    'settings': '<path d="M4 6h4m5 0h7M4 12h10m5 0h1M4 18h2m5 0h9"/><circle cx="10" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
    'terminal': '<path d="m5 7 5 5-5 5m9 0h5"/>',
    'components': '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8M12 13v9"/>',
    'network': '<circle cx="5" cy="12" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><path d="m8 11 8-5M8 13l8 5"/>',
    'cloud': '<path d="M6 18a4 4 0 0 1-1-8 7 7 0 0 1 13-2 5 5 0 0 1 0 10H6Z"/>',
    'appearance': '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/>',
    'warning': '<path d="m12 3 10 18H2L12 3Zm0 6v5m0 3h.01"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
    'external': '<path d="M14 3h7v7m0-7-10 10M10 5H4v15h15v-6"/>',
}


@lru_cache(maxsize=100)
def ui_icon(name, color):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</g></svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for scale in (1, 2, 3):
        pixmap = QPixmap(24 * scale, 24 * scale)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        icon.addPixmap(pixmap)
    return icon


def decorate(widget, name, role='muted'):
    from PySide6.QtWidgets import QApplication
    from .theme import THEMES, normalize_theme
    widget.setProperty('ui_icon', name)
    widget.setProperty('icon_role', role)
    colors = THEMES[normalize_theme(QApplication.instance().property('theme_id'))].colors
    _set_icon(widget, name, colors[role])


def _set_icon(widget, name, color):
    from PySide6.QtWidgets import QLabel
    icon = ui_icon(name, color)
    if isinstance(widget, QLabel):
        widget.setPixmap(icon.pixmap(QSize(24, 24)))
    else:
        widget.setIcon(icon)
        widget.setIconSize(QSize(18, 18))


def refresh_icons(app, colors):
    for widget in app.allWidgets():
        name = widget.property('ui_icon')
        if name:
            _set_icon(widget, name, colors[widget.property('icon_role') or 'muted'])
