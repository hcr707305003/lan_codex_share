"""Generate opaque FRP proxy names without changing existing configurations."""
from uuid import uuid4
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy


def new_proxy_name(existing=()):
    occupied = set(existing)
    while True:
        name = 'codex-share-' + uuid4().hex
        if name not in occupied:
            return name


class ProxyNameEditor(QWidget):
    changed = Signal(str)

    def __init__(self, value, existing, parent=None):
        super().__init__(parent)
        self.existing = set(existing)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit(value)
        self.name.setReadOnly(True)
        self.name.setAccessibleName('FRP 代理名称（可复制）')
        self.name.setToolTip(value)
        row.addWidget(self.name, 1)
        self.generate = QPushButton('重新生成')
        self.generate.setToolTip('仅修改当前代理名称草稿；保存并手动重启 frpc 后生效。')
        self.generate.clicked.connect(self.regenerate)
        row.addWidget(self.generate)

    def text(self):
        return self.name.text()

    def regenerate(self):
        value = new_proxy_name(self.existing | {self.text()})
        self.existing.add(value)
        self.name.setText(value)
        self.name.setToolTip(value)
        self.changed.emit(value)
