"""Pick a workspace while leaving persistence to the configuration form."""
import os
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QSizePolicy


class WorkspacePicker(QWidget):
    changed = Signal(str)

    def __init__(self, value, base_dir, parent=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir).resolve()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.path = QLineEdit(value)
        self.path.setReadOnly(True)
        self.path.setAccessibleName('工作目录路径（只读，可复制）')
        self.path.setPlaceholderText('请选择工作目录')
        self.path.setToolTip(value)
        row.addWidget(self.path, 1)
        self.browse = QPushButton('选择文件夹…')
        self.browse.setAccessibleName('选择工作目录文件夹')
        self.browse.clicked.connect(self.choose_directory)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setObjectName('muted')
        self.feedback.hide()
        layout.addWidget(self.feedback)

    def text(self):
        return self.path.text()

    def _current_directory(self):
        if not self.text().strip():
            return None
        current = Path(self.text().strip()).expanduser()
        return (current if current.is_absolute() else self.base_dir / current).resolve()

    def choose_directory(self):
        try:
            current = self._current_directory()
        except (OSError, ValueError, RuntimeError):
            current = None
        start = current if current is not None and current.is_dir() else self.base_dir
        selected = QFileDialog.getExistingDirectory(self, '选择工作目录', str(start))
        if not selected:
            return
        try:
            chosen = Path(selected).resolve()
            if not chosen.is_dir():
                raise ValueError('目录不存在')
            self.feedback.hide()
            if chosen == current:
                return
            try:
                value = Path(os.path.relpath(chosen, self.base_dir)).as_posix()
            except ValueError:  # Windows drives may have no relative path.
                value = chosen.as_posix()
        except (OSError, ValueError, RuntimeError):
            self.feedback.setText('所选目录不存在或不可读取，请重新选择。')
            self.feedback.show()
            return
        self.path.setText(value)
        self.path.setCursorPosition(0)
        self.path.setToolTip(str(chosen))
        self.changed.emit(value)
