from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QTimer, Signal, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QTextCursor, QFontDatabase
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
                              QPushButton, QStackedWidget, QPlainTextEdit, QLineEdit, QComboBox,
                              QFileDialog, QScrollArea, QApplication, QSizePolicy)

from ..lan_config import load_lan_config
from .app import distribution_directory
from .components_page import ComponentsPage
from .config import ConfigDocument, DesktopSettings
from .config_page import ConfigPage
from .logs import LogBuffer
from .process import ServiceProcess
from .external_monitor import ExternalShareMonitor
from .external_share import inspect_share
from .external_tunnels import inspect_tunnels
from .tunnel_monitor import ExternalTunnelMonitor
from .entries import service_entries, safe_web_url
from .dialogs import confirm_stop
from .messages import MessageBox as QMessageBox
from .theme import apply_theme, set_tone
from .appearance import AppearanceDialog
from .icons import app_icon, decorate


def label(text, style=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    if style:
        widget.setObjectName(style)
    return widget


class DesktopWindow(QMainWindow):
    started = Signal(str, str)

    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = Path(config_path).resolve()
        self.settings = DesktopSettings(self.config_path)
        apply_theme(QApplication.instance(), self.settings.load()['theme'])
        self.setWindowIcon(app_icon())
        self.logs = LogBuffer(self.config_path.parent / 'runtime' / 'desktop')
        self.services = {name: ServiceProcess(name, self.logs) for name in ('Share', 'frpc', 'Tunnel')}
        self.starting = set()
        self.confirming_external = False
        self.confirming_frpc = False
        self.failures = {}
        self.changed_services = set()
        self.exiting = False
        self.paused = False
        self.last_generation = -1
        self.shown_lines = []
        self.filter_key = None
        self.setWindowTitle('LAN Codex Share · 本机控制台')
        self.setMinimumSize(900, 640)
        self.resize(1280, 800)
        root = QWidget()
        self.setCentralWidget(root)
        columns = QHBoxLayout(root)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(192)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(16, 24, 16, 18)
        navigation.setSpacing(6)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(40, 40))
        mark.setFixedSize(40, 40)
        brand.addWidget(mark)
        brand.addWidget(label('LAN Codex\nShare', 'brand'), 1)
        navigation.addLayout(brand)
        navigation.addWidget(label('DESKTOP CONSOLE', 'caption'))
        navigation.addSpacing(22)
        self.nav_buttons = []
        for index, title in enumerate(('服务总览', '配置管理', '组件管理', '运行日志')):
            button = QPushButton(title)
            button.setObjectName('nav')
            decorate(button, ('overview', 'settings', 'components', 'terminal')[index])
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            navigation.addWidget(button)
            self.nav_buttons.append(button)
        navigation.addStretch()
        navigation.addWidget(label('一处管理，多个入口', 'caption'))
        navigation.addWidget(label('外部进程不会自动接管\n隧道独立启动', 'caption'))
        navigation.addSpacing(12)
        self.appearance_button = QPushButton('外观设置')
        decorate(self.appearance_button, 'appearance')
        self.appearance_button.clicked.connect(self.open_appearance)
        navigation.addWidget(self.appearance_button)
        columns.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(28, 26, 28, 18)
        body.setSpacing(16)
        self.title = label('服务总览', 'title')
        body.addWidget(self.title)
        self.subtitle = label('本地服务与公网入口，一目了然。', 'muted')
        body.addWidget(self.subtitle)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        columns.addLayout(body, 1)
        self.status_labels = {}
        self.buttons = {}
        self.overview = self.build_overview()
        self.config_page = ConfigPage(self.config_path, self.settings)
        self.components = ComponentsPage(self.settings)
        self.log_page = self.build_logs()
        for page in (self.overview, self.config_page, self.components, self.log_page):
            if page in (self.config_page, self.log_page):
                # Editors already scroll; keep their toolbars and footer fixed.
                self.stack.addWidget(page)
                continue
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.config_page.saved.connect(self.configuration_saved)
        self.config_page.origin_synced.connect(self.origin_synced)
        self.config_page.tunnel_port_synced.connect(self.tunnel_port_synced)
        self.available = {}
        self.refresh_components()
        self.components.changed.connect(self.refresh_components)
        self.started.connect(self.start_finished)
        self.external = ExternalShareMonitor(self.config_path,
            lambda: self.services['Share'].snapshot()['running'] or 'Share' in self.starting, self)
        self.external.changed.connect(self.refresh)
        self.external.completed.connect(lambda message: self.logs.add('Client', message))
        self.tunnels = ExternalTunnelMonitor(self.settings, self)
        self.tunnels.changed.connect(self.refresh)
        self.tunnels.completed.connect(lambda message: self.logs.add('frpc', message))
        self.refresh_entries()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        self.logs.add('Client', '桌面控制台已就绪，未自动启动服务；正在检测外部 Share 和隧道。外部日志不会自动接入。')
        self.navigate(0)
        self.refresh()
        self.external.start()
        self.tunnels.start()

    def build_overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.entry_labels = {}
        self.entry_buttons = {}
        for name, title, description, kind in [('Share', 'Codex Share', '共享会话与本地服务反代', 'lan'),
                                              ('frpc', 'frpc', '公网 IP + 端口入口', 'frp'),
                                              ('Tunnel', 'Cloudflare', 'Tunnel 域名入口', 'cf')]:
            card = QFrame()
            card.setObjectName('card')
            content = QVBoxLayout(card)
            content.setContentsMargins(18, 18, 18, 18)
            content.setSpacing(10)
            glyph = QLabel()
            glyph.setFixedSize(26, 26)
            decorate(glyph, {'Share': 'terminal', 'frpc': 'network', 'Tunnel': 'cloud'}[name], 'accent')
            content.addWidget(glyph)
            content.addWidget(label(title, 'heading'))
            content.addWidget(label(description, 'muted'))
            state = label('已停止', 'status')
            state.setMinimumHeight(50)
            state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            content.addWidget(state)
            self.status_labels[name] = state
            ports = label('正在读取端口配置…', 'muted')
            ports.setMinimumHeight(70)
            ports.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            content.addWidget(ports)
            self.entry_labels[name] = ports
            open_entry = QPushButton('打开入口 ↗')
            open_entry.setObjectName('entry')
            open_entry.clicked.connect(lambda checked=False, n=name: self.open_entry(n))
            content.addWidget(open_entry)
            self.entry_buttons[name] = open_entry
            actions = QHBoxLayout()
            actions.setSpacing(8)
            button = QPushButton('启动服务')
            button.clicked.connect(lambda checked=False, n=name: self.toggle_service(n))
            actions.addWidget(button, 1)
            self.buttons[name] = button
            configure = QPushButton()
            configure.setFixedWidth(42)
            configure.setAccessibleName(f'编辑 {title} 配置')
            configure.setToolTip(f'编辑 {title} 配置')
            decorate(configure, 'settings')
            configure.clicked.connect(lambda checked=False, k=kind: self.open_config(k))
            actions.addWidget(configure)
            content.addLayout(actions)
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        entry_row = QHBoxLayout()
        self.entry_text = label('端口与入口来自配置；公网可达性未验证。配置修改后，运行中的服务需手动重启生效。', 'muted')
        entry_row.addWidget(self.entry_text, 1)
        layout.addLayout(entry_row)
        layout.addWidget(label('最近日志', 'heading'))
        self.recent = QPlainTextEdit()
        self.recent.setObjectName('log')
        self.recent.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.recent.setReadOnly(True)
        self.recent.setMaximumBlockCount(12)
        self.recent.setMinimumHeight(140)
        layout.addWidget(self.recent, 1)
        return page

    def build_logs(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        toolbar = QHBoxLayout()
        self.log_source = QComboBox()
        self.log_source.addItem('全部服务', '')
        for source in ('Share', 'frpc', 'Tunnel', 'Client'):
            self.log_source.addItem(source, source)
        toolbar.addWidget(self.log_source)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索日志内容…')
        self.search.setAccessibleName('搜索日志')
        toolbar.addWidget(self.search, 1)
        self.pause_button = QPushButton('暂停显示')
        self.pause_button.clicked.connect(self.pause_logs)
        toolbar.addWidget(self.pause_button)
        clear = QPushButton('清空显示')
        clear.clicked.connect(self.logs.clear)
        toolbar.addWidget(clear)
        export = QPushButton('导出日志')
        export.clicked.connect(self.export_logs)
        toolbar.addWidget(export)
        layout.addLayout(toolbar)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName('log')
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(10_000)
        layout.addWidget(self.log_view, 1)
        self.log_count = label('', 'muted')
        layout.addWidget(self.log_count)
        return page

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        self.title.setText(self.nav_buttons[index].text())
        self.subtitle.setText(('本地服务与公网入口，一目了然。', '管理服务配置，保存不会自动重启。',
                               '安装、发现与选择组件；连接由你控制。', '聚合本客户端日志，快速定位运行问题。')[index])

    def open_appearance(self):
        AppearanceDialog(self.settings, self).exec()

    def open_config(self, kind):
        self.config_page.choose_kind(kind)
        self.navigate(1)

    def configuration_saved(self, path):
        names = {'lan': 'Share', 'frp': 'frpc', 'cf': 'Tunnel'}
        self.changed_services.add(names[self.config_page.kind])
        self.refresh_entries()
        self.logs.add('Client', '配置已保存；运行中的服务需手动重启后生效。')
        self.tunnels.scan()

    def origin_synced(self, path):
        self.changed_services.add('Share')
        self.refresh_entries()
        self.logs.add('Client', 'Share 公网入口已同步；运行中的 Share 需手动重启生效。')

    def tunnel_port_synced(self, kind):
        name = 'frpc' if kind == 'frp' else 'Tunnel'
        self.changed_services.add(name)
        self.refresh_entries()
        self.logs.add('Client', f'{name} 本地回源端口已同步；运行中的服务需手动重启生效。')

    def refresh_components(self):
        self.available = {'frpc': bool(self.components.executable('frpc')),
                          'Tunnel': bool(self.components.executable('cloudflared'))}
        self.changed_services.update(['frpc', 'Tunnel'])
        if hasattr(self, 'tunnels'):
            self.tunnels.scan()
            self.refresh_entries()

    def refresh_entries(self):
        self.entries = service_entries(self.config_path, self.settings)
        for name, entry in self.entries.items():
            text = entry.text + ('\n' + entry.url if entry.url else '')
            self.entry_labels[name].setText(text)
            self.entry_labels[name].setToolTip(entry.detail)
            button = self.entry_buttons[name]
            button.setText('打开本地网页 ↗' if name == 'Share' else '打开公网入口 ↗' if entry.url else '未配置公网入口')
            button.setEnabled(bool(entry.url))
            button.setToolTip(entry.url or ('请检查 LAN 配置' if name == 'Share' else '请在 LAN 配置填写对应的公网入口'))

    def open_entry(self, name):
        url = safe_web_url(self.entries[name].url)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def secrets_from(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if any(word in str(key).lower() for word in ('password', 'token', 'secret')) and isinstance(item, str):
                    self.logs.set_secrets([item])
                else:
                    self.secrets_from(item)
        elif isinstance(value, list):
            for item in value:
                self.secrets_from(item)

    def command(self, name):
        values = self.settings.load()
        if name == 'Share':
            data = ConfigDocument(self.config_path, 'lan').parse(self.config_path.read_text(encoding='utf-8-sig'))
            self.secrets_from(data)
            load_lan_config(self.config_path)
            if getattr(sys, 'frozen', False):
                binary = distribution_directory() / ('lan_codex_share.exe' if os.name == 'nt' else 'lan_codex_share')
                if not binary.is_file():
                    raise ValueError('发行目录缺少配套 lan_codex_share 程序')
                return [str(binary), '_desktop-worker', str(self.config_path)], self.config_path.parent, True
            return [sys.executable, '-u', '-m', 'lan_codex_share.desktop.worker', str(self.config_path)], distribution_directory(), True
        component = 'frpc' if name == 'frpc' else 'cloudflared'
        binary = self.components.executable(component)
        if not binary:
            raise ValueError(f'未找到 {component}，请前往组件管理选择或下载')
        if name == 'frpc':
            config = self.settings.resolve(values['frpc_config'])
            self.secrets_from(ConfigDocument(config, 'frp').validate(config.read_text(encoding='utf-8-sig')))
            return [binary, '-c', str(config)], config.parent, False
        if values['cloudflared_mode'] == 'token-file':
            if not values['cloudflared_token_file']:
                raise ValueError('尚未选择 Cloudflare token 文件')
            token_file = self.settings.resolve(values['cloudflared_token_file'])
            if token_file.stat().st_size > 64 * 1024:
                raise ValueError('token 文件过大，请检查所选文件')
            self.logs.set_secrets([token_file.read_text(encoding='utf-8').strip()])
            help_result = subprocess.run([binary, 'tunnel', 'run', '--help'], capture_output=True, timeout=10,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if b'--token-file' not in help_result.stdout + help_result.stderr:
                raise ValueError('当前 cloudflared 不支持 --token-file，请升级或使用本地 YAML 模式')
            return [binary, 'tunnel', 'run', '--token-file', str(token_file)], self.settings.path.parent, False
        config = self.settings.resolve(values['cloudflared_config'])
        ConfigDocument(config, 'cf').validate(config.read_text(encoding='utf-8-sig'))
        return [binary, 'tunnel', '--config', str(config), 'run'], config.parent, False

    def toggle_service(self, name):
        if name == 'frpc' and (self.tunnels.busy or self.confirming_frpc):
            return
        service = self.services[name]
        state = service.snapshot()
        if state['running']:
            force = state['timed_out']
            details = '目标：本客户端启动的服务\n' + self.entries[name].text
            if force:
                details += '\n清理已超时，仅强制结束本客户端创建的进程。'
            if confirm_stop(self, name, force=force, details=details):
                service.force_stop() if force else service.stop()
            return
        if name in self.starting:
            return
        if name in self.tunnels.states and self.tunnels.states[name].status != 'stopped':
            external = self.tunnels.states[name]
            if name == 'frpc' and external.identity is not None:
                self.confirming_frpc = True
                self.refresh()
                try:
                    if confirm_stop(self, '外部 FRP', force=True,
                            details=f'PID {external.identity.pid}\n配置：{external.identity.config_path}\n关闭会中断此 FRP 公网入口；不会关闭 Share 或其他业务进程。'):
                        if not self.tunnels.close_frpc(external.identity):
                            self.logs.add('Client', 'FRP 身份或状态已变化，已取消关闭，请重新检测。')
                finally:
                    self.confirming_frpc = False
                    self.refresh()
            self.tunnels.scan()
            return
        if name == 'Share':
            if self.external.busy or self.confirming_external:
                return
            external = self.external.state
            if external.identity is not None:
                self.confirming_external = True
                self.refresh()
                try:
                    if confirm_stop(self, '外部 Share', force=True,
                        details=f'PID {external.identity.pid}\n配置：{self.config_path}\n只处理已验证的 Share 及其自建 App Server，不递归关闭业务进程。'):
                        if not self.external.force_close(external.identity):
                            self.logs.add('Client', '进程身份或状态已变化，已取消强制关闭，请重新检测。')
                            self.external.scan()
                finally:
                    self.confirming_external = False
                    self.refresh()
                return
            if external.status != 'stopped':
                self.external.scan()
                return
        if name in self.available and not self.available[name]:
            self.navigate(2)
            return
        self.starting.add(name)
        self.failures.pop(name, None)

        def work():
            try:
                if name == 'Share':
                    external = inspect_share(self.config_path)
                    if external.status != 'stopped':
                        raise ValueError('未启动新 Share：' + external.message)
                else:
                    external = inspect_tunnels(self.settings)[name]
                    if external.status != 'stopped':
                        raise ValueError('未启动新隧道：' + external.message)
                argv, cwd, controlled = self.command(name)
                if name != 'Share':
                    external = inspect_tunnels(self.settings)[name]
                    if external.status != 'stopped':
                        raise ValueError('未启动新隧道：' + external.message)
                service.start(argv, cwd, controlled=controlled)
                self.started.emit(name, '')
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else '启动失败，请检查程序、配置文件、权限与依赖'
                self.started.emit(name, self.logs.redact(message))
        threading.Thread(target=work, daemon=True).start()
        self.refresh()

    def start_finished(self, name, error):
        self.starting.discard(name)
        if error:
            self.failures[name] = error
            self.logs.add(name, error)
        else:
            self.changed_services.discard(name)
        if name == 'Share':
            self.external.scan()
        else:
            self.tunnels.scan()

    def refresh(self):
        if self.exiting and any(p.snapshot()['timed_out'] for p in self.services.values()):
            self.exiting = False
            self.logs.add('Client', '服务仍在清理，已取消自动退出。可继续等待或选择强制停止。')
        statuses = []
        for name, service in self.services.items():
            state = service.snapshot()
            text = '启动中' if name in self.starting else '已停止'
            if name in self.available and not self.available[name]:
                text = '未安装或未选择程序'
            if state['running']:
                text = '已就绪' if state['ready'] else '启动中' if name == 'Share' else '进程运行中（公网状态未验证）'
            if state['stopping']:
                text = '停止中，请等待' if not state['timed_out'] else '清理超过 15 秒，可继续等待或强制停止'
            if name in self.failures:
                text = self.failures[name]
            elif state['exit_code'] not in (None, 0) and not state['running']:
                text = f'进程已退出，代码 {state["exit_code"]}，请查看日志'
            if name in self.changed_services and state['running']:
                text += '\n配置已变更，重启后生效'
            self.status_labels[name].setText(text)
            self.status_labels[name].setToolTip(text)
            statuses.append(f'{name}: {"运行中" if state["running"] else "已停止"}')
            missing = name in self.available and not self.available[name]
            self.buttons[name].setText('强制停止…' if state['timed_out'] else '停止服务' if state['running'] else '安装 / 选择程序' if missing else '启动服务')
            self.buttons[name].setEnabled(name not in self.starting and (not state['stopping'] or state['timed_out']) and not self.exiting)
            if name in self.tunnels.states and not state['running'] and name not in self.starting:
                external = self.tunnels.states[name]
                if external.status != 'stopped':
                    self.status_labels[name].setText(external.message)
                    summary = {'running': '外部运行中', 'unverified': '外部运行 / 配置未确认',
                               'checking': '检测中', 'transition': '服务状态切换中',
                               'multiple': '多个外部实例', 'unknown': '无法验证'}[external.status]
                    statuses[-1] = f'{name}: {summary}'
                    self.buttons[name].setText('外部运行 / 请检查' if external.pids else '等待检测 / 请检查')
                    self.buttons[name].setEnabled(False)
                    if name == 'frpc' and external.identity is not None:
                        self.buttons[name].setText('正在关闭…' if self.tunnels.busy else '关闭外部 FRP…')
                        self.buttons[name].setEnabled(not self.tunnels.busy and not self.confirming_frpc and not self.exiting)
                self.status_labels[name].setToolTip(external.message)
            if name == 'Share' and not state['running'] and name not in self.starting:
                external = self.external.state
                text = '正在强制关闭外部 Share…' if self.external.busy else external.message
                if external.status == 'stopped' and name in self.failures:
                    text = self.failures[name]
                self.status_labels[name].setText(text)
                statuses[-1] = 'Share: ' + text.replace('\n', ' ')
                self.buttons[name].setText('强制关闭…' if external.identity else '启动服务' if external.status == 'stopped' else '等待检测 / 请检查配置')
                self.buttons[name].setEnabled((external.identity is not None or external.status == 'stopped')
                    and not self.external.busy and not self.confirming_external and not self.exiting)
            tone = 'muted'
            if state['running']:
                tone = 'success' if name == 'Share' and state['ready'] else 'warning'
            if name in self.starting or state['stopping'] or name in self.changed_services and state['running']:
                tone = 'warning'
            if name == 'Share' and not state['running'] and self.external.state.identity:
                tone = 'warning' if self.external.busy else 'success'
            if name in self.tunnels.states and not state['running'] and self.tunnels.states[name].status != 'stopped':
                tone = 'warning'
            if name in self.failures or state['timed_out'] or state['exit_code'] not in (None, 0) and not state['running']:
                tone = 'danger'
            set_tone(self.status_labels[name], tone)
            desired_style = 'primary' if self.buttons[name].text() == '启动服务' and self.buttons[name].isEnabled() else ''
            if self.buttons[name].objectName() != desired_style:
                self.buttons[name].setObjectName(desired_style)
                self.buttons[name].style().unpolish(self.buttons[name])
                self.buttons[name].style().polish(self.buttons[name])
        self.statusBar().showMessage(' · '.join(statuses))
        if not self.paused:
            key = (self.log_source.currentData(), self.search.text())
            if self.last_generation != self.logs.generation or key != self.filter_key:
                rows = self.logs.filtered(*key)
                if key == self.filter_key and rows[:len(self.shown_lines)] == self.shown_lines:
                    added = rows[len(self.shown_lines):]
                    if added:
                        self.log_view.appendPlainText('\n'.join(added))
                else:
                    self.log_view.setPlainText('\n'.join(rows))
                self.shown_lines = rows
                self.filter_key = key
                self.recent.setPlainText('\n'.join(self.logs.filtered()[-12:]))
                self.recent.moveCursor(QTextCursor.End)
                self.last_generation = self.logs.generation
                self.log_count.setText(f'显示 {len(rows)} 条 · 超出容量丢弃 {self.logs.dropped} 条；导出前请检查业务敏感内容。')
        if self.exiting and not self.starting and not self.components.busy and not any(p.snapshot()['running'] for p in self.services.values()):
            self.close()

    def pause_logs(self):
        self.paused = not self.paused
        self.pause_button.setText('继续显示' if self.paused else '暂停显示')

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出当前筛选日志（请检查业务敏感内容）', 'desktop-log.txt', '文本 (*.txt)')
        if path:
            try:
                Path(path).write_text('\n'.join(self.logs.filtered(self.log_source.currentData(), self.search.text())), encoding='utf-8')
            except OSError:
                QMessageBox.warning(self, '导出失败', '无法写入所选文件，请检查目录权限。')

    def closeEvent(self, event):
        if self.external.busy or self.confirming_external or self.tunnels.busy or self.confirming_frpc:
            QMessageBox.information(self, '关闭操作进行中', '请等待外部服务关闭操作或确认对话框结束。')
            event.ignore()
            return
        if self.starting:
            QMessageBox.information(self, '启动中', '请等待当前启动操作结束后再关闭。')
            event.ignore()
            return
        if not self.exiting and not self.config_page.discard():
            event.ignore()
            return
        if not self.exiting and not self.components.discard():
            event.ignore()
            return
        running = any(service.snapshot()['running'] for service in self.services.values())
        if running or self.components.busy:
            if not self.exiting:
                names = '、'.join(n for n, s in self.services.items() if s.snapshot()['running'])
                if not confirm_stop(self, '本客户端服务', exiting=True, details='停止范围：' + (names or '无运行服务') + '\n取消本客户端的组件下载，不关闭外部服务。'):
                    event.ignore()
                    return
                self.exiting = True
                self.components.cancel.set()
                for service in self.services.values():
                    service.stop()
            # Keep the window usable for an explicit force stop after timeout.
            if any(p.snapshot()['timed_out'] for p in self.services.values()):
                self.exiting = False
            event.ignore()
            return
        self.timer.stop()
        self.external.close()
        self.tunnels.close()
        self.logs.close()
        event.accept()
