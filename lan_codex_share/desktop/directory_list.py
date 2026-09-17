"""Preview-root selection edits configuration only, never directories on disk."""
import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QFileDialog, QLabel


class DirectoryListEditor(QWidget):
    changed = Signal(list)

    def __init__(self, values, base_dir, parent=None):
        super().__init__(parent)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError('preview_roots 必须是目录字符串数组')
        self.base_dir = Path(base_dir).resolve()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.list = QListWidget()
        self.list.setAccessibleName('预览目录列表')
        self.list.setMinimumHeight(90)
        self.list.setMaximumHeight(150)
        self.list.addItems(values)
        self._tooltips()
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.add = QPushButton('添加目录…')
        self.add.clicked.connect(self.add_directory)
        row.addWidget(self.add)
        self.remove = QPushButton('移除选中目录')
        self.remove.setEnabled(False)
        self.remove.clicked.connect(self.remove_selected)
        row.addWidget(self.remove)
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel('相对配置文件保存；移除只改配置，不删除目录。')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        layout.addWidget(hint)
        self.list.currentRowChanged.connect(lambda row: self.remove.setEnabled(row >= 0))

    def values(self):
        return [self.list.item(index).text() for index in range(self.list.count())]

    def resolved(self, value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else self.base_dir / path).resolve()

    def _tooltips(self):
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setToolTip(item.text())

    def add_directory(self):
        chosen = QFileDialog.getExistingDirectory(self, '添加预览目录', str(self.base_dir))
        if chosen:
            self.add_path(chosen)

    def add_path(self, path):
        chosen = Path(path).expanduser().resolve()
        if chosen in [self.resolved(value) for value in self.values()]:
            return
        try:
            value = Path(os.path.relpath(chosen, self.base_dir)).as_posix()
        except ValueError:  # Different Windows drives have no relative path.
            value = chosen.as_posix()
        self.list.addItem(value)
        self._tooltips()
        self.list.setCurrentRow(self.list.count() - 1)
        self.changed.emit(self.values())

    def remove_selected(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.changed.emit(self.values())
