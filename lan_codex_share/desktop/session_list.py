"""Edit Session sharing scope without connecting to or deleting real sessions."""
import json
import re

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                              QComboBox, QListWidget, QPlainTextEdit, QPushButton, QLabel)


def parse_session_input(text):
    text = text.strip()
    if not text:
        return []
    if text.startswith('['):
        try:
            values = json.loads(text)
        except ValueError:
            raise ValueError('Session 数组格式错误，请输入字符串数组。') from None
    else:
        values = [part.strip() for part in re.split(r'[,，\r\n]+', text) if part.strip()]
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip()
        or re.search(r'\s|[\[\]{}"\',，]', value.strip()) for value in values
    ):
        raise ValueError('请输入非空 Session ID，不能包含空白、引号或数组分隔符。')
    return list(dict.fromkeys(value.strip() for value in values))


class SessionListEditor(QWidget):
    changed = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)
        if 'session_id' in data and 'session_ids' in data:
            raise ValueError('session_id 与 session_ids 不能同时配置，请在原始配置中修正。')
        if 'session_ids' in data:
            values = data['session_ids']
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError('session_ids 必须是非空 ID 字符串组成的数组，空数组表示共享全部。')
            values = [v.strip() for v in values]
            if len(values) != len(set(values)):
                raise ValueError('session_ids 存在重复 ID，请在原始配置中修正。')
            mode = 'selected' if values else 'all'
        else:
            value = data.get('session_id', '')
            if not isinstance(value, str):
                raise ValueError('session_id 必须是字符串。')
            values = [value.strip()] if value.strip() else []
            mode = 'selected' if values else 'auto'
        self._mode = mode
        self._modified = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.mode = QComboBox()
        self.mode.setAccessibleName('Session 共享模式')
        for title, key in [('指定会话', 'selected'), ('共享全部', 'all'), ('自动单会话', 'auto')]:
            self.mode.addItem(title, key)
        self.mode.setCurrentIndex(self.mode.findData(mode))
        layout.addWidget(self.mode)
        self.scope_hint = QLabel()
        self.scope_hint.setWordWrap(True)
        self.scope_hint.setObjectName('muted')
        layout.addWidget(self.scope_hint)
        self.entries = QWidget()
        entry_layout = QVBoxLayout(self.entries)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(8)
        self.list = QListWidget()
        self.list.setAccessibleName('指定 Session 列表')
        self.list.setMinimumHeight(90)
        self.list.setMaximumHeight(130)
        self.list.addItems(values)
        self._tooltips()
        entry_layout.addWidget(self.list)
        row = QHBoxLayout()
        self.copy = QPushButton('复制 ID')
        self.copy.clicked.connect(self.copy_selected)
        self.remove = QPushButton('移除选中项')
        self.remove.clicked.connect(self.remove_selected)
        row.addWidget(self.copy)
        row.addWidget(self.remove)
        row.addStretch()
        entry_layout.addLayout(row)
        label = QLabel('添加 Session ID（支持多行、逗号或 JSON 数组）')
        label.setWordWrap(True)
        entry_layout.addWidget(label)
        self.input = QPlainTextEdit()
        self.input.setAccessibleName('待添加的 Session ID')
        self.input.setPlaceholderText('粘贴 ID 后点击「添加到列表」')
        self.input.setFixedHeight(68)
        self.input.setTabChangesFocus(True)
        label.setBuddy(self.input)
        entry_layout.addWidget(self.input)
        self.add = QPushButton('添加到列表')
        self.add.clicked.connect(self.add_input)
        entry_layout.addWidget(self.add)
        layout.addWidget(self.entries)
        self.feedback = QLabel()
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.input.textChanged.connect(self.changed.emit)
        self.list.currentRowChanged.connect(self._selection_changed)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._selection_changed()
        self._render_mode()

    def values(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def dirty(self):
        return self._modified or bool(self.input.toPlainText().strip())

    def changes(self):
        if self.input.toPlainText().strip():
            raise ValueError('还有未添加的 Session ID，请先添加到列表或清空输入。')
        if self._mode == 'selected' and not self.values():
            raise ValueError('指定会话至少需要一个 ID；如需共享全部，请明确切换模式。')
        if not self._modified:
            return {}, ()
        if self._mode == 'auto':
            return {}, ('session_ids', 'session_id')
        return {'session_ids': self.values() if self._mode == 'selected' else []}, ('session_id',)

    def mark_applied(self):
        self._modified = False

    def _tooltips(self):
        for i in range(self.list.count()):
            self.list.item(i).setToolTip(self.list.item(i).text())

    def _selection_changed(self, *_):
        selected = self.list.currentRow() >= 0
        self.copy.setEnabled(selected)
        self.remove.setEnabled(selected)

    def _render_mode(self):
        self.entries.setVisible(self._mode == 'selected')
        self.scope_hint.setText({
            'selected': '仅共享列表内会话。移除只改配置，不删除真实会话。',
            'all': '共享所有可发现会话，按项目分组。请确认访问范围。',
            'auto': '沿用缺省行为：复用或创建一个会话，不列出全部会话。',
        }[self._mode])

    def _mode_changed(self, *_):
        if self.input.toPlainText().strip():
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData(self._mode))
            self.mode.blockSignals(False)
            self.feedback.setText('请先添加或清空待添加的 ID，再切换模式。')
            return
        self._mode = self.mode.currentData()
        self._modified = True
        self.feedback.clear()
        self._render_mode()
        self.changed.emit()

    def add_input(self):
        try:
            added = parse_session_input(self.input.toPlainText())
        except ValueError as exc:
            self.feedback.setText(str(exc))
            return
        current = self.values()
        merged = list(dict.fromkeys(current + added))
        if merged != current:
            self.list.clear()
            self.list.addItems(merged)
            self._tooltips()
            self.list.setCurrentRow(len(merged) - 1)
            self._modified = True
        self.input.clear()
        self.feedback.setText(f'已添加 {len(merged) - len(current)} 项，重复项已忽略。' if added else '')
        self.changed.emit()

    def remove_selected(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self._modified = True
            self.feedback.setText('列表已空，请添加 ID 或明确切换共享模式。' if not self.values() else '已从配置列表移除，尚未保存。')
            self.changed.emit()

    def copy_selected(self):
        item = self.list.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.text())
            self.feedback.setText('已复制选中 ID。')
