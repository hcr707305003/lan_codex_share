"""Consistent, bounded and plain-text application prompts (not file pickers)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QWidget, QMessageBox as QtMessageBox)
from .icons import decorate, app_icon


class MessageDialog(QDialog):
    def __init__(self, parent, title, text, *, question=False, severity='info', action='继续'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(520, 310)
        self.setMinimumSize(420, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        glyph = QLabel()
        glyph.setFixedSize(28, 28)
        decorate(glyph, 'info' if severity == 'info' else 'warning', 'accent' if severity == 'info' else 'danger')
        layout.addWidget(glyph)
        heading = QLabel(title)
        heading.setObjectName('heading')
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.PlainText)
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        self.body = QLabel(text)
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.PlainText)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.body.setObjectName('muted')
        content_layout.addWidget(self.body)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel = QPushButton('取消')
        self.cancel.clicked.connect(self.reject)
        self.cancel.setVisible(question)
        self.cancel.setDefault(question)
        row.addWidget(self.cancel)
        self.confirm = QPushButton(action if question else '知道了')
        self.confirm.setObjectName('danger' if question and severity != 'info' else 'primary')
        self.confirm.setAutoDefault(not question)
        self.confirm.setDefault(not question)
        self.confirm.clicked.connect(self.accept)
        row.addWidget(self.confirm)
        layout.addLayout(row)
        (self.cancel if question else self.confirm).setFocus()


class MessageBox:
    """Small compatibility surface for the application's current message call sites."""
    Yes = QtMessageBox.Yes
    No = QtMessageBox.No
    Ok = QtMessageBox.Ok

    @staticmethod
    def question(parent, title, text, buttons=None, default=None):
        action = '下载并安装' if title == '安装官方 frpc' else '放弃修改'
        dialog = MessageDialog(parent, title, text, question=True, severity='warning', action=action)
        return MessageBox.Yes if dialog.exec() == QDialog.Accepted else MessageBox.No

    @staticmethod
    def information(parent, title, text, *args):
        MessageDialog(parent, title, text).exec()
        return MessageBox.Ok

    @staticmethod
    def warning(parent, title, text, *args):
        MessageDialog(parent, title, text, severity='warning').exec()
        return MessageBox.Ok

    critical = warning
