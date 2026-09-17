"""Offline desktop themes, independent of service configuration and state."""
from dataclasses import dataclass
from string import Template
from types import MappingProxyType
from typing import Mapping
from pathlib import Path


@dataclass(frozen=True)
class Theme:
    name: str
    description: str
    colors: Mapping[str, str]


def _theme(name, description, **colors):
    return Theme(name, description, MappingProxyType(colors))


THEMES = {
    'graphite': _theme('石墨薄荷', '沉静深色 · 推荐默认', bg='#141718', sidebar='#191d1e', card='#1d2223',
        text='#edf3ef', muted='#a0aea7', line='#46534c', accent='#a4e7c6', on_accent='#153729',
        soft='#263f34', input='#171c1d', hover='#303a35', disabled='#77837c', success='#a4e7c6',
        warning='#edc785', danger='#f0aaa5', danger_bg='#442e2e', selection='#385c49'),
    'forest': _theme('暖白森林', '暖白底色 · 日间办公', bg='#f4f6f2', sidebar='#ebefea', card='#ffffff',
        text='#24362c', muted='#627368', line='#9cae9e', accent='#245b43', on_accent='#ffffff',
        soft='#e3eee5', input='#f8faf7', hover='#dbe8df', disabled='#829085', success='#246343',
        warning='#80530b', danger='#9f3637', danger_bg='#fae9e6', selection='#245b43'),
    'midnight': _theme('午夜蓝', '冷调深蓝 · 技术感', bg='#101827', sidebar='#131f30', card='#192638',
        text='#edf3ff', muted='#a3b4cc', line='#516783', accent='#a1c5ff', on_accent='#172e50',
        soft='#263b57', input='#142033', hover='#2b405c', disabled='#7e8da3', success='#9be0bd',
        warning='#efd094', danger='#f5ada8', danger_bg='#492d39', selection='#36577e'),
    'lavender': _theme('柔和紫', '浅色紫调 · 轻柔清爽', bg='#f5f3f9', sidebar='#eeebf4', card='#ffffff',
        text='#30273e', muted='#70657f', line='#aa9bbc', accent='#71519b', on_accent='#ffffff',
        soft='#ede5f6', input='#f8f5fc', hover='#e5d9f0', disabled='#93859f', success='#286449',
        warning='#80530b', danger='#9f343b', danger_bg='#fae9ee', selection='#71519b'),
}


def normalize_theme(value):
    return value if isinstance(value, str) and value in THEMES else 'graphite'


_QSS = Template('''
QWidget { color: $text; font-size: 13px; }
QMainWindow, QDialog { background: $bg; }
QFrame#sidebar { background: $sidebar; border: none; border-right: 1px solid $soft; }
QFrame#card, QFrame#panel, QFrame#componentCard { background: $card; border: 1px solid $soft; border-radius: 12px; }
QFrame#panel { background: $input; border-radius: 8px; }
QLabel { background: transparent; border: none; }
QLabel#title { font-size: 24px; font-weight: 600; }
QLabel#heading { font-size: 16px; font-weight: 600; }
QLabel#brand { font-size: 15px; font-weight: 600; }
QLabel#muted, QLabel#caption { color: $muted; }
QLabel#caption { font-size: 11px; }
QLabel[tone="success"] { color: $success; }
QLabel[tone="warning"] { color: $warning; }
QLabel[tone="danger"] { color: $danger; }
QLabel#status { font-size: 12px; }
QLabel[tone="muted"] { color: $muted; }
QPushButton, QToolButton { background: $card; border: 2px solid $soft; border-radius: 8px; padding: 8px 12px; }
QPushButton:hover, QToolButton:hover { background: $hover; border-color: $line; }
QPushButton:pressed, QToolButton:pressed { background: $soft; }
QPushButton:checked, QPushButton#primary { background: $accent; color: $on_accent; border-color: $accent; }
QPushButton#primary:hover { border-color: $text; }
QPushButton#nav { text-align: left; background: transparent; border-color: transparent; padding: 10px 12px; color: $muted; }
QPushButton#nav:hover { background: $hover; }
QPushButton#nav:checked { background: $soft; color: $accent; }
QPushButton#entry { text-align: left; background: $input; font-size: 12px; }
QPushButton#danger { background: $danger_bg; color: $danger; border-color: $danger_bg; }
QPushButton#danger:hover { border-color: $danger; }
QPushButton:disabled, QToolButton:disabled { color: $disabled; background: $input; border-color: $soft; }
QPushButton:focus, QToolButton:focus { border-color: $accent; }
QPushButton#primary:focus, QPushButton#danger:focus { border-color: $text; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox { background: $input; color: $text; border: 2px solid $line; padding: 7px; border-radius: 7px; selection-background-color: $selection; selection-color: #ffffff; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: $accent; }
QLineEdit[invalid="true"] { border-color: $danger; }
QLineEdit:disabled, QComboBox:disabled { color: $disabled; border-color: $soft; }
QListWidget { background: $input; color: $text; border: 2px solid $line; border-radius: 7px; padding: 4px; }
QListWidget:focus { border-color: $accent; }
QListWidget::item { padding: 5px 7px; border-radius: 4px; }
QListWidget::item:selected { background: $selection; color: #ffffff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("$chevron"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $card; color: $text; selection-background-color: $selection; selection-color: #ffffff; border: 1px solid $line; outline: none; }
QPlainTextEdit#log, QPlainTextEdit#code { font-size: 12px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: $bg; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: $bg; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $line; min-height: 28px; border-radius: 3px; }
QScrollBar::handle:horizontal { background: $line; min-width: 28px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: $sidebar; color: $muted; border-top: 1px solid $soft; font-size: 11px; }
QStatusBar::item { border: none; }
QToolTip { background: $card; color: $text; border: 1px solid $line; padding: 6px; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $line; border-radius: 4px; }
QCheckBox::indicator:checked { background: $accent; }
QProgressBar { border: 1px solid $line; border-radius: 5px; background: $input; text-align: center; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QPushButton#themeChoice { text-align: left; background: $card; padding: 14px; border: 2px solid $line; }
QPushButton#themeChoice:checked { color: $text; border-color: $accent; background: $soft; }
QPushButton#themeChoice:focus { border-color: $text; }
''')


def stylesheet(theme_id):
    theme_id = normalize_theme(theme_id)
    chevron = (Path(__file__).resolve().parent / 'assets' / f'chevron-{theme_id}.svg').as_posix()
    return _QSS.substitute(THEMES[theme_id].colors, chevron=chevron)


STYLE = stylesheet('graphite')


def set_tone(widget, tone):
    if widget.property('tone') != tone:
        widget.setProperty('tone', tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def apply_theme(app, theme_id):
    from PySide6.QtGui import QColor, QPalette
    theme_id = normalize_theme(theme_id)
    style = stylesheet(theme_id)
    if app.property('theme_id') == theme_id and app.styleSheet() == style:
        return theme_id
    c = THEMES[theme_id].colors
    palette = QPalette()
    roles = {'Window': 'bg', 'WindowText': 'text', 'Base': 'input', 'AlternateBase': 'card',
             'Text': 'text', 'Button': 'card', 'ButtonText': 'text', 'ToolTipBase': 'card',
             'ToolTipText': 'text', 'PlaceholderText': 'muted', 'Link': 'accent', 'Highlight': 'selection'}
    for role, color in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(c[color]))
    palette.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(c['disabled']))
    app.setPalette(palette)
    app.setStyleSheet(style)
    app.setProperty('theme_id', theme_id)
    from .icons import refresh_icons
    refresh_icons(app, c)
    return theme_id
