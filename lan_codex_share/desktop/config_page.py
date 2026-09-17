from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
                              QComboBox, QPlainTextEdit, QLineEdit, QFileDialog, QScrollArea, QSizePolicy, QCheckBox)
from .messages import MessageBox as QMessageBox

from .config import ConfigDocument, DesktopSettings, _digest
from .origin_sync import prepare_sync
from .tunnel_port_sync import prepare_port_sync
from ..lan_config import LanConfig, load_lan_config
from .origin_dialog import choose_origin
from .directory_list import DirectoryListEditor
from .session_list import SessionListEditor
from .workspace_picker import WorkspacePicker
from .proxy_name import ProxyNameEditor, new_proxy_name
from .cloudflare_form import CloudflareForm, share_url
from .cloudflare_form_data import update_fields as update_cloudflare_fields
from .form_help import with_field_help


TEMPLATES = {
    'lan': 'workspace = "."\nhost = "0.0.0.0"\nport = 9000\napp_server_port = 4500\nsession_ids = []\npermission_mode = "workspace-write"\npassword = ""\ncloudflare_origin = ""\nfrp_origin = ""\n',
    'frp': 'serverAddr = "192.0.2.10"\nserverPort = 7000\nauth.method = "token"\nauth.token = ""\ntransport.tls.enable = true\n\n[[proxies]]\nname = "codex-share"\ntype = "tcp"\nlocalIP = "127.0.0.1"\nlocalPort = 9000\nremotePort = 20000\n',
    'cf': 'tunnel: replace-with-your-tunnel-id\ncredentials-file: ./tunnel-credentials.json\ningress:\n  - hostname: codex.example.com\n    service: http://localhost:9000\n  - service: http_status:404\n',
}
FIELDS = {
    'lan': [('workspace', '工作目录', 'workspace'), ('host', '监听地址', 'str'), ('port', 'Web 端口', 'int'),
            ('app_server_port', 'App Server 端口', 'int'), ('session_ids', 'Session 共享范围', 'sessions'),
            ('permission_mode', '权限', 'permission'), ('password', '项目密码', 'secret'),
            ('notify_on_task_complete', '任务结束提示', 'checkbox'),
            ('preview_roots', '预览目录', 'directories'), ('cloudflare_origin', 'Cloudflare 入口', 'str'), ('frp_origin', 'FRP 入口', 'str')],
    'frp': [('proxies.name', '代理名称', 'proxy_name'), ('serverAddr', '服务器地址', 'str'), ('serverPort', '控制端口', 'int'), ('auth.token', '认证 Token', 'secret'),
            ('transport.tls.enable', 'TLS（true / false）', 'bool'), ('proxies.localIP', '代理本地地址', 'str'),
            ('proxies.localPort', '代理本地端口', 'int'), ('proxies.remotePort', '代理公网端口', 'int')],
    'cf': [],
}


class ConfigPage(QWidget):
    saved = Signal(str)
    origin_synced = Signal(str)
    tunnel_port_synced = Signal(str)

    def __init__(self, lan_path: Path, settings: DesktopSettings, parent=None):
        super().__init__(parent)
        self.lan_path, self.settings = lan_path, settings
        self.kind = 'lan'
        self.document = None
        self.baseline = ''
        self.updates = {}
        self.editors = {}
        self.form_mode = False
        self.cf_form = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        toolbar = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setMinimumContentsLength(12)
        self.kind_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for label, key in [('Share · lan_config.toml', 'lan'), ('frpc.toml', 'frp'), ('Cloudflare YAML', 'cf')]:
            self.kind_combo.addItem(label, key)
        toolbar.addWidget(self.kind_combo)
        for title, callback in [('打开文件', self.open_file), ('创建示例', self.create_example), ('重新加载', self.reload)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.path_label.setMaximumHeight(44)
        self.path_label.setObjectName('muted')
        layout.addWidget(self.path_label)
        modebar = QHBoxLayout()
        self.mode = QPushButton('返回表单编辑')
        self.mode.setToolTip('高级文件编辑可直接修改完整配置文本，包含密码和 Token；请勿分享敏感内容。')
        self.mode.clicked.connect(self.toggle_mode)
        modebar.addWidget(self.mode)
        self.proxy = QComboBox()
        self.proxy.setMinimumContentsLength(18)
        self.proxy.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.proxy.setAccessibleName('选择 TCP 代理')
        self.proxy.currentIndexChanged.connect(self.change_proxy)
        modebar.addWidget(self.proxy)
        modebar.addStretch()
        layout.addLayout(modebar)
        self.raw = QPlainTextEdit()
        self.raw.setObjectName('code')
        self.raw.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.raw.setMinimumHeight(180)
        self.raw.setAccessibleName('高级文件编辑：完整配置文本，可能包含密码和 Token')
        self.raw.setPlaceholderText('选择已有配置或创建示例。原始配置可能显示密码，请勿直接分享截图。')
        layout.addWidget(self.raw, 1)
        self.form_area = QScrollArea()
        self.form_area.setWidgetResizable(True)
        self.form_widget = QWidget()
        # Let the scroll content allocate the form's full height after rows change
        # (e.g. hiding Session entries), instead of compressing complex fields.
        content_layout = QVBoxLayout(self.form_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.form = QFormLayout()
        content_layout.addLayout(self.form)
        content_layout.addStretch()
        self.form.setContentsMargins(18, 16, 18, 16)
        self.form.setVerticalSpacing(14)
        self.form.setHorizontalSpacing(20)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form_area.setWidget(self.form_widget)
        layout.addWidget(self.form_area, 1)
        self.form_area.hide()
        self.message = QLabel('保存只写配置，不会自动重启服务。原始配置包含敏感内容。')
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        self.message.setObjectName('muted')
        layout.addWidget(self.message)
        row = QHBoxLayout()
        save_copy = QPushButton('另存副本')
        save_copy.clicked.connect(self.save_copy)
        row.addWidget(save_copy)
        row.addStretch()
        button = QPushButton('校验并保存')
        button.setObjectName('primary')
        button.clicked.connect(lambda: self.save())
        row.addWidget(button)
        layout.addLayout(row)
        self.kind_combo.currentIndexChanged.connect(self.change_kind)
        self.load_path(lan_path)

    def dirty(self):
        session = self.editors.get('session_ids')
        session_dirty = self.form_mode and isinstance(session, SessionListEditor) and session.dirty()
        cf_dirty = self.form_mode and self.cf_form is not None and self.cf_form.dirty()
        return session_dirty or cf_dirty or bool(self.updates) or any(e.property('invalid') for e in self.editors.values()) or self.raw.toPlainText() != self.baseline

    def discard(self):
        return not self.dirty() or QMessageBox.question(self, '未保存修改', '放弃当前未保存的配置修改？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def path_for_kind(self):
        if self.kind == 'lan':
            return self.lan_path
        return self.settings.resolve(self.settings.load()['frpc_config' if self.kind == 'frp' else 'cloudflared_config'])

    def load_path(self, path):
        self.document = ConfigDocument(Path(path), self.kind)
        self.path_label.setText(str(self.document.path))
        self.path_label.setToolTip(str(self.document.path))
        self.updates.clear()
        self.cf_form = None
        self.editors.clear()
        self.form_mode = False
        self.form_area.hide()
        self.raw.show()
        self.mode.setText('返回表单编辑')
        self.mode.setEnabled(True)
        self.proxy.setVisible(False)
        try:
            text = self.document.load() if self.document.path.exists() else ''
            self.raw.setPlainText(text)
            self.baseline = self.raw.toPlainText()
            self.message.setText('配置已加载；原始配置可能显示密钥。保存不会重启服务。' if text else '配置文件不存在，请打开文件或创建示例。')
            if text:
                self.toggle_mode()
        except (OSError, ValueError, UnicodeError) as exc:
            self.message.setText(f'加载失败：{type(exc).__name__}，请检查文件和编码')

    def change_kind(self):
        selected = self.kind_combo.currentData()
        if selected == self.kind:
            return
        if not self.discard():
            self.kind_combo.blockSignals(True)
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(self.kind))
            self.kind_combo.blockSignals(False)
            return
        self.kind = selected
        self.load_path(self.path_for_kind())

    def choose_kind(self, kind):
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(kind))

    def open_file(self):
        if not self.discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, '打开配置', str(self.settings.path.parent), '配置 (*.toml *.yaml *.yml);;所有文件 (*)')
        if name:
            if self.kind == 'lan' and Path(name).resolve() != self.lan_path:
                self.message.setText('切换整个项目请使用启动参数 --config 指定另一份 LAN 配置。')
                return
            if self.kind != 'lan':
                self.settings.save({'frpc_config' if self.kind == 'frp' else 'cloudflared_config': name})
            self.load_path(Path(name))

    def create_example(self):
        if not self.discard():
            return
        if self.document.path.exists():
            self.message.setText('目标文件已存在，不覆盖。请使用打开文件编辑。')
            return
        text = TEMPLATES[self.kind]
        if self.kind == 'frp':
            text = self.document.update_fields(text, {'proxies.name': new_proxy_name()})
        if self.kind == 'cf':
            try:
                text = update_cloudflare_fields(text, {'service': share_url(self.lan_path)}, 0)
            except ValueError as exc:
                self.message.setText(str(exc))
                return
        self.updates.clear()
        self.raw.setPlainText(text)
        self.message.setText('示例尚未保存，请先填写实际配置；不会自动连接任何服务。')
        self.form_mode = False
        self.toggle_mode()

    def reload(self):
        if self.discard():
            self.load_path(self.document.path)

    def apply_form(self):
        if self.kind == 'cf' and self.cf_form is not None:
            self.raw.setPlainText(self.cf_form.apply())
            self.cf_form.mark_applied()
            return
        if any(editor.property('invalid') for editor in self.editors.values()):
            raise ValueError('请修正表单格式错误，当前输入已保留')
        updates = dict(self.updates)
        remove_fields = ()
        session = self.editors.get('session_ids')
        if isinstance(session, SessionListEditor):
            session_updates, remove_fields = session.changes()
            updates.update(session_updates)
        if updates or remove_fields:
            self.raw.setPlainText(self.document.update_fields(self.raw.toPlainText(), updates,
                                  self.proxy.currentData() or 0, remove_fields=remove_fields))
            self.updates.clear()
            if isinstance(session, SessionListEditor):
                session.mark_applied()

    def toggle_mode(self):
        try:
            if self.form_mode:
                self.apply_form()
            else:
                self.populate_form()
            self.form_mode = not self.form_mode
            self.form_area.setVisible(self.form_mode)
            self.raw.setVisible(not self.form_mode)
            self.proxy.setVisible(self.form_mode and self.kind == 'frp')
            self.mode.setText('高级文件编辑' if self.form_mode else '返回表单编辑')
        except ValueError as exc:
            self.message.setText(str(exc))

    def change_proxy(self):
        if self.form_mode:
            # Flush edits against the previous proxy before changing selection.
            current = self.proxy.currentIndex()
            self.proxy.blockSignals(True)
            self.proxy.setCurrentIndex(getattr(self, '_proxy_index', 0))
            try:
                self.apply_form()
            except ValueError as exc:
                self.proxy.blockSignals(False)
                self.message.setText(str(exc))
                return
            self.proxy.setCurrentIndex(current)
            self.proxy.blockSignals(False)
            self.populate_form(keep_proxy=True)

    def populate_form(self, keep_proxy=False):
        data = self.document.parse(self.raw.toPlainText())
        cf_form = None
        if self.kind == 'cf':
            cf_form = CloudflareForm(self.raw.toPlainText(), self.document.path, self.lan_path,
                                     self.settings.load()['cloudflared_mode'] != 'yaml')
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors.clear()
        self.cf_form = cf_form
        if cf_form is not None:
            cf_form.changed.connect(lambda: self.message.setText('Cloudflare 配置已修改，尚未保存；不会自动重启服务。'))
            self.form.addRow(cf_form)
            return
        if self.kind == 'frp' and not keep_proxy:
            self.proxy.blockSignals(True)
            self.proxy.clear()
            for index, proxy in enumerate(data.get('proxies', [])):
                if isinstance(proxy, dict) and proxy.get('type') == 'tcp':
                    self.proxy.addItem(str(proxy.get('name', f'代理 {index + 1}')), index)
            self.proxy.blockSignals(False)
        self._proxy_index = self.proxy.currentIndex()
        for key, title, kind in FIELDS[self.kind]:
            value = data
            parts = key.split('.')
            if parts[0] == 'proxies':
                index = self.proxy.currentData()
                if index is None:
                    continue
                value = data['proxies'][index]
                parts = parts[1:]
            for part in parts:
                value = value.get(part) if isinstance(value, dict) else None
            if kind == 'proxy_name':
                existing = [p.get('name', '') for p in data.get('proxies', []) if isinstance(p, dict) and isinstance(p.get('name', ''), str)]
                editor = ProxyNameEditor(str(value) if value is not None else '', existing)
                editor.changed.connect(self.proxy_name_changed)
            elif kind == 'workspace':
                editor = WorkspacePicker(str(value) if value is not None else '', self.document.path.parent)
                editor.changed.connect(lambda text, k=key: self.field_changed(k, 'str', text))
            elif kind == 'sessions':
                editor = SessionListEditor(data)
                editor.changed.connect(lambda: self.message.setText('Session 设置尚未保存；仅修改共享范围，不操作真实会话。'))
            elif kind == 'directories':
                editor = DirectoryListEditor(value if value is not None else [], self.document.path.parent)
                editor.changed.connect(lambda values, k=key: self.directories_changed(k, values))
            elif kind == 'checkbox':
                if value is not None and not isinstance(value, bool):
                    raise ValueError(f'{key} 必须是布尔值')
                editor = QCheckBox('开启网页常驻提示（需手动关闭）')
                editor.setToolTip('重启 Share 并刷新网页后生效；保存不会自动重启服务。')
                editor.setChecked(value is True)
                editor.toggled.connect(lambda checked, k=key: self.checkbox_changed(k, checked))
            elif kind == 'permission':
                editor = QComboBox()
                editor.addItems(['read-only', 'workspace-write', 'danger-full-access'])
                editor.setCurrentText(str(value or 'danger-full-access'))
                editor.currentTextChanged.connect(lambda text, k=key: self.updates.__setitem__(k, text))
            else:
                text = '' if value is None else json.dumps(value, ensure_ascii=False) if kind in ('json', 'bool') else str(value)
                editor = QLineEdit(text)
                if kind == 'secret':
                    editor.setEchoMode(QLineEdit.Password)
                editor.textEdited.connect(lambda text, k=key, t=kind: self.field_changed(k, t, text))
            editor.setAccessibleName(title)
            self.editors[key] = editor
            field_label = QLabel(title)
            field_label.setWordWrap(True)
            field_label.setFixedWidth(165)
            if key == 'proxies.localPort':
                row = QHBoxLayout()
                row.addWidget(editor, 1)
                button = QPushButton('应用 Share 端口')
                button.setToolTip('读取已保存的 Share 端口，仅修改当前代理的本地端口草稿，不改变公网端口或本地地址。')
                button.setAccessibleName('应用 Share 端口到当前 FRP 代理本地端口')
                button.clicked.connect(self.apply_share_port)
                row.addWidget(button)
                self.form.addRow(field_label, with_field_help(row, editor, self.kind, key))
            else:
                self.form.addRow(field_label, with_field_help(editor, editor, self.kind, key))

    def apply_share_port(self):
        editor = self.editors.get('proxies.localPort')
        if self.kind != 'frp' or not self.form_mode or editor is None:
            return
        try:
            port = str(load_lan_config(self.lan_path).port)
        except (OSError, ValueError):
            self.message.setText('无法读取有效的 Share 配置，请先校验并保存 Share 配置；原本地端口保持不变。')
            return
        if editor.text() == port and not editor.property('invalid'):
            self.message.setText('当前本地端口已与 Share 一致，无需修改。')
            return
        editor.setText(port)
        self.field_changed('proxies.localPort', 'int', port)
        self.message.setText(f'已应用 Share 端口 {port}，尚未保存；仅修改当前代理本地端口，保存后需手动重启 frpc 生效。')

    def proxy_name_changed(self, text):
        self.updates['proxies.name'] = text
        self.proxy.setItemText(self.proxy.currentIndex(), text)
        self.message.setText('代理名称已生成，尚未保存；保存并手动重启 frpc 后生效。公网端口仍需独立分配。')

    def checkbox_changed(self, key, checked):
        self.updates[key] = checked
        self.message.setText('配置已修改，尚未保存。重启 Share 并刷新网页后生效。')

    def directories_changed(self, key, values):
        self.updates[key] = values
        self.message.setText('预览目录已修改，尚未保存。移除配置项不会删除磁盘目录。')

    def field_changed(self, key, kind, text):
        try:
            value = int(text) if kind == 'int' else json.loads(text) if kind in ('json', 'bool') else text
            if kind == 'json' and not isinstance(value, list):
                raise ValueError()
            if kind == 'bool' and not isinstance(value, bool):
                raise ValueError()
            self.updates[key] = value
            self.message.setText('配置已修改，尚未保存。')
            self.editors[key].setProperty('invalid', False)
        except ValueError:
            self.editors[key].setProperty('invalid', True)
            self.message.setText(f'{key} 格式错误，请输入有效整数、数组或 true/false')

    def save(self, *, sync_entries=True):
        try:
            if self.form_mode and any(editor.property('invalid') for editor in self.editors.values()):
                raise ValueError('请修正表单格式错误后保存')
            if self.form_mode:
                self.apply_form()
            proposals = self.prepare_tunnel_ports() if sync_entries and self.kind == 'lan' else []
            self.document.save(self.raw.toPlainText())
            self.baseline = self.raw.toPlainText()
            port_message = self.sync_tunnel_ports(proposals)
            self.saved.emit(str(self.document.path))
            message = self.sync_origin() if sync_entries and self.kind in ('frp', 'cf') else '已保存。运行中的服务需手动重启后生效。'
            self.message.setText(port_message or message)
            return True
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc) if isinstance(exc, ValueError) else '文件不可写，请检查目录权限')
            return False

    @staticmethod
    def port_sync_error(exc):
        if isinstance(exc, FileNotFoundError):
            return '配置文件不存在，请先配置隧道'
        if isinstance(exc, OSError):
            return '配置文件不可读写，请检查目录和权限'
        if isinstance(exc, UnicodeError):
            return '配置文件编码错误，请使用 UTF-8'
        return str(exc) if isinstance(exc, ValueError) else '配置结构不支持自动同步，请手动检查'

    def prepare_tunnel_ports(self):
        if not self.baseline or self.document.digest is None:
            return []  # New configuration has no previous Share upstream to identify.
        try:
            old = int(self.document.parse(self.baseline).get('port', LanConfig.port))
            new = int(self.document.parse(self.raw.toPlainText()).get('port', LanConfig.port))
        except (ValueError, TypeError):
            return []  # The normal Share validation reports invalid edits.
        if old == new:
            return []
        results = []
        for kind, key in (('frp', 'frpc_config'), ('cf', 'cloudflared_config')):
            try:
                settings = self.settings.load()
                if kind == 'cf' and settings['cloudflared_mode'] != 'yaml':
                    raise ValueError('Token 模式请在 Cloudflare 控制台修改回源端口')
                proposal = prepare_port_sync(self.settings.resolve(settings[key]), kind, old, new)
                results.append((kind, key, proposal, ''))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                results.append((kind, key, None, self.port_sync_error(exc)))
        return results

    def sync_tunnel_ports(self, proposals):
        messages = []
        for kind, key, proposal, error in proposals:
            name = 'FRP' if kind == 'frp' else 'Cloudflare'
            if proposal is not None:
                try:
                    settings = self.settings.load()
                    if (self.settings.resolve(settings[key]) != proposal.document.path or
                            (kind == 'cf' and settings['cloudflared_mode'] != 'yaml')):
                        raise ValueError('隧道配置选择或启动模式已变化，请重新检查回源端口')
                    if _digest(self.document.path) != self.document.digest:
                        raise ValueError('Share 配置已被外部修改，请重新检查回源端口')
                    count = proposal.apply()
                    self.tunnel_port_synced.emit(kind)
                    messages.append(f'{name} 已同步 {count} 条本地回源端口')
                    continue
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    error = self.port_sync_error(exc)
            messages.append(f'{name} 未同步：{error}')
        return ('Share 已保存。' + '；'.join(messages) + '。运行中的 Share 和已同步隧道需手动重启后生效。') if messages else ''

    def sync_origin(self):
        prefix = '隧道配置已保存，Share 入口未同步：'
        try:
            data = self.document.parse(self.baseline)
            mode = self.settings.load()['cloudflared_mode'] if self.kind == 'cf' else 'yaml'
            proposal = prepare_sync(self.lan_path, self.kind, data, mode)
            if not proposal.candidates:
                return prefix + proposal.reason
            origin = choose_origin(self, proposal) if proposal.needs_choice else proposal.candidates[0]
            if origin is None:
                return prefix + '已取消同步，原入口保持不变。'
            if _digest(self.document.path) != self.document.digest:
                return prefix + '隧道配置已被外部修改，请重新加载后再保存。'
            if (self.document.path != self.path_for_kind() or
                    (self.kind == 'cf' and self.settings.load()['cloudflared_mode'] != mode)):
                return prefix + '当前隧道配置选择或启动模式已变化，请重新加载后再保存。'
            changed = proposal.apply(origin)
            if changed:
                self.origin_synced.emit(str(self.lan_path))
            return ('隧道配置已保存，已同步 ' if changed else '隧道配置已保存，入口已一致，无需同步：') + proposal.field + '。运行中的服务需手动重启后生效。'
        except ValueError as exc:
            return prefix + str(exc)
        except OSError:
            return prefix + '配置文件不可读写，请检查目录和权限。'
        except (TypeError, KeyError):
            return prefix + '配置结构无法用于同步，请检查隧道规则。'

    def save_copy(self):
        try:
            if self.form_mode:
                self.apply_form()
            path, _ = QFileDialog.getSaveFileName(self, '另存配置副本（不会切换当前服务配置）',
                                                 str(self.document.path.with_stem(self.document.path.stem + '-copy')))
            if not path:
                return
            copy = ConfigDocument(Path(path), self.kind)
            if copy.path == self.document.path:
                self.save(sync_entries=False)
                return
            copy.save(self.raw.toPlainText())
            self.message.setText('副本已保存。当前服务仍使用原配置；LAN 相对路径按副本目录校验。')
        except (ValueError, OSError) as exc:
            self.message.setText(str(exc) if isinstance(exc, ValueError) else '无法写入副本，请检查目标目录权限')
