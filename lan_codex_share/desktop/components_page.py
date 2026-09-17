from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import os
import threading
import re

from PySide6.QtCore import Signal, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
                              QComboBox, QLineEdit, QFormLayout, QFrame, QSizePolicy)
from .messages import MessageBox as QMessageBox

from .config import DesktopSettings
from . import installer
from .app import distribution_directory
from .discovery import Discovery, discover, usable


class ComponentsPage(QWidget):
    changed = Signal()
    result = Signal(str, object)
    progress = Signal(str)

    def __init__(self, settings: DesktopSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.cancel = threading.Event()
        self.busy = False
        self.release = None
        self.labels = {}
        self.discoveries = {}
        self.candidates = {}
        self.candidate_rows = {}
        self.candidate_buttons = {}
        self.choose_buttons = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = QLabel('组件与 Tunnel 启动配置')
        title.setObjectName('heading')
        layout.addWidget(title)
        hint = QLabel('只安装或选择程序，不自动启动连接。Codex CLI 仍使用本机已安装的命令。')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        for name, url in [('frpc', installer.RELEASES_URL), ('cloudflared', 'https://github.com/cloudflare/cloudflared/releases')]:
            card = QFrame()
            card.setObjectName('componentCard')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            row = QHBoxLayout()
            label = QLabel()
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setTextInteractionFlags(label.textInteractionFlags())
            row.addWidget(label, 1)
            self.labels[name] = label
            select = QPushButton('选择本地程序')
            select.clicked.connect(lambda checked=False, n=name: self.choose(n))
            self.choose_buttons.append(select)
            row.addWidget(select)
            official = QPushButton('官方下载页 ↗')
            official.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(official)
            card_layout.addLayout(row)
            candidates_row = QWidget()
            candidates_layout = QHBoxLayout(candidates_row)
            candidates_layout.setContentsMargins(0, 0, 0, 0)
            candidates = QComboBox()
            candidates.setAccessibleName(f'{name} 可用程序路径')
            candidates.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            candidates.setMinimumContentsLength(20)
            candidates_layout.addWidget(candidates, 1)
            use = QPushButton('使用所选程序')
            use.setEnabled(False)
            candidates.currentIndexChanged.connect(lambda index, b=use: b.setEnabled(index > 0))
            use.clicked.connect(lambda checked=False, n=name: self.use_candidate(n))
            candidates_layout.addWidget(use)
            self.candidates[name] = candidates
            self.candidate_rows[name] = candidates_row
            self.candidate_buttons[name] = use
            candidates_row.hide()
            card_layout.addWidget(candidates_row)
            layout.addWidget(card)
        self.scan_button = QPushButton('重新扫描默认路径')
        self.scan_button.clicked.connect(self.rescan)
        layout.addWidget(self.scan_button)
        actions = QHBoxLayout()
        self.download_button = QPushButton('获取 frpc 官方稳定版')
        self.download_button.setObjectName('primary')
        self.download_button.clicked.connect(self.fetch_release)
        actions.addWidget(self.download_button)
        self.cancel_button = QPushButton('取消操作')
        self.cancel_button.clicked.connect(self.cancel.set)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)
        version_button = QPushButton('检测组件版本（不会连接服务）')
        version_button.clicked.connect(self.probe_versions)
        layout.addWidget(version_button)
        self.version_label = QLabel('Codex CLI：尚未检测版本')
        self.version_label.setTextFormat(Qt.PlainText)
        self.version_label.setWordWrap(True)
        self.version_label.setObjectName('muted')
        layout.addWidget(self.version_label)
        self.message = QLabel('下载会验证官方 SHA-256；无法验证时只提供手动下载指引。')
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        self.message.setObjectName('muted')
        layout.addWidget(self.message)
        tunnel_card = QFrame()
        tunnel_card.setObjectName('componentCard')
        tunnel_layout = QVBoxLayout(tunnel_card)
        tunnel_layout.setContentsMargins(18, 16, 18, 16)
        tunnel_layout.setSpacing(14)
        tunnel_title = QLabel('Cloudflare 启动设置')
        tunnel_title.setObjectName('heading')
        tunnel_layout.addWidget(tunnel_title)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setVerticalSpacing(12)
        self.mode = QComboBox()
        self.mode.addItem('本地 YAML 配置', 'yaml')
        self.mode.addItem('远程管理 Tunnel · token 文件', 'token-file')
        self.token_file = QLineEdit()
        self.token_file.setPlaceholderText('只填写 token 文件路径，不在此输入 token 内容')
        self.token_file.setAccessibleName('Cloudflare token 文件路径')
        token_row = QHBoxLayout()
        token_row.addWidget(self.token_file)
        choose_token = QPushButton('选择文件')
        choose_token.clicked.connect(self.select_token)
        token_row.addWidget(choose_token)
        form.addRow('Cloudflare 启动模式', self.mode)
        form.addRow('Token 文件', token_row)
        tunnel_layout.addLayout(form)
        save = QPushButton('保存 Tunnel 启动设置')
        save.clicked.connect(self.save_mode)
        tunnel_layout.addWidget(save)
        note = QLabel('本地 YAML 在“配置管理”中编辑；token 文件模式不把 token 放进命令行。保存设置不会重启进程。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        tunnel_layout.addWidget(note)
        layout.addWidget(tunnel_card)
        layout.addStretch()
        self.result.connect(self.finished)
        self.progress.connect(self.message.setText)
        values = self.settings.load()
        self.mode.setCurrentIndex(max(0, self.mode.findData(values['cloudflared_mode'])))
        self.token_file.setText(values['cloudflared_token_file'])
        self.saved_mode = (self.mode.currentData(), self.token_file.text())
        self.refresh()
        self.rescan()

    def executable(self, name):
        value = self.settings.load()[f'{name}_executable']
        if value:
            path = self.settings.resolve(value)
            return str(path) if usable(path) else None
        result = self.discoveries.get(name, Discovery())
        if not result.incomplete and len(result.candidates) == 1 and usable(result.candidates[0]):
            return str(result.candidates[0])
        return None

    def rescan(self):
        if self.busy:
            return
        roots = (distribution_directory(), self.settings.path.parent)
        self.discoveries.clear()
        self.refresh()
        self.changed.emit()
        self.message.setText('正在扫描程序目录、配置目录、bin 版本子目录及 PATH…')
        self.run_job('scan', lambda: {name: discover(name, roots, cancel=self.cancel)
                                     for name in ('frpc', 'cloudflared')})

    def save_program(self, name, file):
        path = Path(file)
        if not usable(path):
            raise ValueError('程序已不存在或不可执行，请重新扫描或选择')
        self.settings.save({f'{name}_executable': self.settings.program_value(path)})
        self.refresh()
        self.changed.emit()

    def use_candidate(self, name):
        file = self.candidates[name].currentData()
        if not file or self.busy:
            return
        try:
            self.save_program(name, file)
            self.message.setText('已保存所选程序，未启动或切换运行中的服务。')
        except (OSError, ValueError):
            self.message.setText('无法使用所选程序，请检查文件权限或重新扫描。')

    def refresh(self):
        values = self.settings.load()
        for name, label in self.labels.items():
            executable = self.executable(name)
            result = self.discoveries.get(name, Discovery())
            explicit = values[f'{name}_executable']
            if executable:
                status = executable
            elif explicit:
                status = f'指定路径失效或不可执行：{self.settings.resolve(explicit)}\n请重新选择程序。'
            elif result.incomplete:
                status = '扫描未完成（数量上限或目录不可读），请选择可信程序。'
            elif len(result.candidates) > 1:
                status = f'发现 {len(result.candidates)} 个程序，请选择要使用的版本。'
            else:
                status = '未找到程序，请重新扫描、手动选择或下载。'
            label.setText(f'{name}\n{status}')
            choices = self.candidates[name]
            choices.clear()
            choices.addItem('请选择程序路径…', None)
            for path in result.candidates:
                choices.addItem(str(path), str(path))
            self.candidate_rows[name].setVisible(bool(result.candidates) and
                (len(result.candidates) > 1 or result.incomplete or bool(explicit and not executable)))

    def choose(self, name):
        file, _ = QFileDialog.getOpenFileName(self, f'选择可信的 {name} 程序', str(self.settings.path.parent))
        if file:
            try:
                self.save_program(name, file)
            except (OSError, ValueError):
                self.message.setText('无法保存程序位置，请检查桌面配置文件及目录权限')

    def select_token(self):
        file, _ = QFileDialog.getOpenFileName(self, '选择 Cloudflare token 文件')
        if file:
            self.token_file.setText(file)

    def save_mode(self):
        try:
            path = self.token_file.text().strip()
            if self.mode.currentData() == 'token-file' and (not path or not self.settings.resolve(path).is_file()):
                raise ValueError('请选择已存在的 token 文件')
            self.settings.save({'cloudflared_mode': self.mode.currentData(), 'cloudflared_token_file': path})
            self.saved_mode = (self.mode.currentData(), self.token_file.text())
            self.message.setText('已保存启动设置，需手动重启 Tunnel 后生效。')
            self.changed.emit()
        except (ValueError, OSError) as exc:
            self.message.setText(str(exc) if isinstance(exc, ValueError) else '保存失败，请检查目录权限')

    def discard(self):
        current = (self.mode.currentData(), self.token_file.text())
        return current == self.saved_mode or QMessageBox.question(self, '未保存的 Tunnel 设置',
            '放弃未保存的 Tunnel 启动模式或 token 文件设置？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def run_job(self, kind, operation):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.scan_button.setEnabled(False)
        for row in self.candidate_rows.values():
            row.setEnabled(False)
        self.download_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        for button in self.choose_buttons:
            button.setEnabled(False)

        def work():
            try:
                value = operation()
                self.result.emit(kind, value)
            except PermissionError:
                self.result.emit('error', '安装目录不可写或程序文件被占用，请检查目录权限，或将客户端放到可写目录后重试；未切换所选程序。'
                                 if kind == 'installed' else '操作失败，请检查文件及目录访问权限。')
            except Exception as exc:
                self.result.emit('error', str(exc) if isinstance(exc, ValueError) else '操作失败，请检查网络、磁盘空间或文件权限')
        threading.Thread(target=work, daemon=True).start()

    def fetch_release(self):
        self.message.setText('正在获取官方稳定版信息…')
        self.run_job('release', lambda: installer.latest_release(self.cancel))

    def probe_versions(self):
        commands = {name: self.executable(name) for name in ('frpc', 'cloudflared')}
        commands['Codex CLI'] = shutil.which('codex.cmd' if os.name == 'nt' else 'codex') or shutil.which('codex.exe')

        def probe():
            versions = []
            for name, binary in commands.items():
                if self.cancel.is_set():
                    raise ValueError('检测已取消')
                version = '未找到程序'
                if binary:
                    try:
                        result = subprocess.run([binary, '--version'], capture_output=True, timeout=5,
                                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                        match = re.search(rb'\b\d+\.\d+\.\d+\b', result.stdout[:4096] + result.stderr[:4096])
                        version = match.group().decode('ascii') if match and result.returncode == 0 else '版本检测失败'
                    except (OSError, subprocess.TimeoutExpired):
                        version = '无法运行或检测超时'
                versions.append(f'{name}: {version}')
            return ' · '.join(versions)
        self.run_job('versions', probe)

    def finished(self, kind, result):
        self.busy = False
        self.scan_button.setEnabled(True)
        for row in self.candidate_rows.values():
            row.setEnabled(True)
        self.download_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        for button in self.choose_buttons:
            button.setEnabled(True)
        if self.cancel.is_set():
            self.message.setText('操作已取消，未改变所选程序。')
            return
        if kind == 'scan':
            self.discoveries = result
            self.refresh()
            self.changed.emit()
            self.message.setText('默认路径扫描完成，未运行任何程序。' if not any(r.incomplete for r in result.values())
                                 else '部分目录不可读或达到扫描上限，请手动选择可信程序。')
        elif kind == 'release':
            version = str(result.get('tag_name', ''))
            destination = distribution_directory() / 'bin' / 'frp'
            answer = QMessageBox.question(self, '安装官方 frpc',
                                          f'下载并校验 {version}？\n安装目录：{destination / version.removeprefix("v")}\n安装后不会自动启动连接。',
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.run_job('installed', lambda: installer.install_frpc(result, destination, self.cancel, self.progress.emit))
        elif kind == 'installed':
            try:
                self.save_program('frpc', result)
                self.message.setText('frpc 已安装并通过校验；请到服务总览手动启动。')
            except (ValueError, OSError):
                self.message.setText('安装完成，但程序位置保存失败。请手动选择安装后的 frpc。')
        elif kind == 'versions':
            self.version_label.setText(str(result))
            self.message.setText('版本检测完成，未启动任何服务连接。')
        else:
            self.message.setText(str(result))
