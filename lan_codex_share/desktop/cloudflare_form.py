"""Local Cloudflare form; all edits remain drafts until ConfigPage saves."""
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                              QLineEdit, QPushButton, QComboBox, QFileDialog, QSizePolicy)

from ..lan_config import load_lan_config
from .cloudflare_form_data import form_data, update_fields, validate_field
from .form_help import with_field_help


def share_url(lan_path):
    try:
        config = load_lan_config(lan_path)
    except (OSError, ValueError):
        raise ValueError('Share 配置不可用，请先校验并保存 Share 配置') from None
    return f'http://localhost:{config.port}'


class CloudflareForm(QWidget):
    changed = Signal()

    def __init__(self, text, config_path, lan_path, token_mode=False, parent=None):
        data, rules = form_data(text)
        super().__init__(parent)
        self.config_path, self.lan_path = Path(config_path), Path(lan_path)
        self._text = self._initial = text
        self._updates = {}
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.info = QLabel('当前为 Token 模式：此处仅编辑本地 YAML，不会更新 Cloudflare 远程回源；启动模式保持不变。'
                           if token_mode else '编辑本地 Tunnel 配置。仅保存你修改的字段，其他规则与注释保留。')
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.PlainText)
        self.info.setObjectName('muted')
        layout.addWidget(self.info)
        form = QFormLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(14)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        layout.addLayout(form)
        self.rules = QComboBox(self)
        self.rules.setMinimumContentsLength(18)
        self.rules.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.rules.setAccessibleName('选择已有 Cloudflare 域名入口')
        for index, rule in rules:
            self.rules.addItem(f'{index + 1} · {rule["hostname"]}', index)
        if len(rules) > 1:
            form.addRow('入口规则', with_field_help(self.rules, self.rules, 'cf', 'ingress'))
        else:
            self.rules.hide()
        self._selected = 0
        self._rule_index = self.rules.currentData()
        for key, title in [('tunnel', 'Tunnel ID / 名称'), ('credentials-file', '凭证 JSON 文件'),
                           ('hostname', '公网域名'), ('service', '本地回源地址')]:
            field = QLineEdit()
            field.setAccessibleName(title)
            field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.fields[key] = field
            field.textEdited.connect(lambda value, k=key: self.edit(k, value))
            row = QHBoxLayout()
            row.addWidget(field, 1)
            if key == 'credentials-file':
                self.browse = QPushButton('选择文件…')
                self.browse.setAccessibleName('选择 Cloudflare 凭证 JSON 文件')
                self.browse.clicked.connect(self.choose_credentials)
                row.addWidget(self.browse)
            elif key == 'service':
                self.use_share = QPushButton('使用 Share 地址')
                self.use_share.setToolTip('使用已保存 Share 配置的端口，仅更新草稿，不启停服务。')
                self.use_share.clicked.connect(self.follow_share)
                row.addWidget(self.use_share)
            label = QLabel(title)
            label.setFixedWidth(165)
            label.setBuddy(field)
            form.addRow(label, with_field_help(row, field, 'cf', key))
        self.fields['hostname'].setPlaceholderText('codex.example.com（不带 https://）')
        self.fields['service'].setPlaceholderText('http://localhost:9000')
        self.feedback = QLabel()
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        self.feedback.setObjectName('muted')
        self.feedback.setAccessibleName('Cloudflare 表单提示')
        layout.addWidget(self.feedback)
        self._fill(data)
        self.rules.currentIndexChanged.connect(self.change_rule)

    def _fill(self, data):
        rule = data['ingress'][self._rule_index]
        self._values = {key: data.get(key, '') if key in ('tunnel', 'credentials-file') else rule[key]
                        for key in self.fields}
        for key, field in self.fields.items():
            field.setText(self._values[key])
            field.setProperty('invalid', False)

    def edit(self, key, value):
        if value == self._values[key]:
            self._updates.pop(key, None)
        else:
            self._updates[key] = value
        self.fields[key].setProperty('invalid', False)
        self.feedback.setText('尚未保存；不会自动重启服务。')
        self.changed.emit()

    def _flush(self):
        for key, value in self._updates.items():
            try:
                validate_field(key, value)
            except ValueError as exc:
                field = self.fields[key]
                field.setProperty('invalid', True)
                field.setFocus()
                message = field.accessibleName() + '：' + str(exc)
                self.feedback.setText(message)
                raise ValueError(message) from None
        self._text = update_fields(self._text, self._updates, self._rule_index)
        self._updates.clear()
        data, _ = form_data(self._text)
        self._fill(data)
        self.rules.setItemText(self._selected, f'{self._rule_index + 1} · {data["ingress"][self._rule_index]["hostname"]}')

    def change_rule(self, selected):
        try:
            self._flush()
        except ValueError as exc:
            self.rules.blockSignals(True)
            self.rules.setCurrentIndex(self._selected)
            self.rules.blockSignals(False)
            self.feedback.setText(str(exc))
            return
        self._selected = selected
        self._rule_index = self.rules.currentData()
        data, _ = form_data(self._text)
        self._fill(data)

    def dirty(self):
        return bool(self._updates) or self._text != self._initial

    def apply(self):
        self._flush()
        return self._text

    def mark_applied(self):
        self._initial = self._text

    def choose_credentials(self):
        chosen, _ = QFileDialog.getOpenFileName(self, '选择 Cloudflare 凭证 JSON 文件',
                                               str(self.config_path.parent), 'JSON 文件 (*.json);;所有文件 (*)')
        if not chosen:
            return
        try:
            path = Path(chosen).resolve()
            if not path.is_file() or path.suffix.lower() != '.json':
                raise ValueError()
        except (OSError, ValueError):
            self.feedback.setText('请选择存在的 JSON 凭证文件；不会读取或显示文件内容。')
            return
        value = path.as_posix()  # Absolute paths do not depend on cloudflared's working directory.
        self.fields['credentials-file'].setText(value)
        self.edit('credentials-file', value)

    def follow_share(self):
        try:
            value = share_url(self.lan_path)
        except ValueError as exc:
            self.feedback.setText(str(exc))
            return
        self.fields['service'].setText(value)
        self.edit('service', value)
