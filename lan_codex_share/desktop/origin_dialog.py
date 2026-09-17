"""Explicit selection for conflicting or ambiguous public entry candidates."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QPushButton, QFrame, QLayout, QScrollArea, QSizePolicy)
from .icons import app_icon, decorate


class OriginDialog(QDialog):
    def __init__(self, parent, proposal):
        super().__init__(parent)
        self.setWindowTitle('同步 Share 公网入口')
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(440)
        self.resize(580, 450)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        glyph = QLabel()
        glyph.setFixedSize(28, 28)
        decorate(glyph, 'network', 'accent')
        layout.addWidget(glyph)
        title = QLabel('同步公网入口？')
        title.setObjectName('heading')
        layout.addWidget(title)
        description = QLabel('隧道配置已保存。请选择写入 Share 的入口；取消会保留原入口，不影响已保存的隧道配置。')
        description.setObjectName('muted')
        description.setWordWrap(True)
        layout.addWidget(description)
        panel = QFrame()
        panel.setObjectName('panel')
        fields = QVBoxLayout(panel)
        fields.setContentsMargins(14, 12, 14, 12)
        self.current = QLabel(f'{proposal.field}\n当前入口：{proposal.current or "未设置"}')
        self.current.setTextFormat(Qt.PlainText)
        self.current.setWordWrap(True)
        self.current.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.current.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fields.addWidget(self.current)
        self.candidates = QComboBox()
        self.candidates.setAccessibleName('选择同步到 Share 的公网入口')
        self.candidates.setMinimumContentsLength(25)
        self.candidates.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.candidates.addItems(proposal.candidates)
        fields.addWidget(self.candidates)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.PlainText)
        self.preview.setWordWrap(True)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fields.addWidget(self.preview)
        self.candidates.currentTextChanged.connect(self.update_preview)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(100)
        scroll.setMaximumHeight(220)
        scroll.setWidget(panel)
        layout.addWidget(scroll, 1)
        note = QLabel('只更新入口配置，不启停服务。保存后需你手动重启 Share 生效；HTTP 入口不加密浏览器传输。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.wrapped = [(description, 52), (self.current, 96), (self.preview, 96), (note, 52)]
        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel = QPushButton('取消同步')
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        self.confirm = QPushButton('同步到 Share')
        self.confirm.setObjectName('primary')
        self.confirm.setAutoDefault(False)
        self.confirm.setDefault(False)
        self.confirm.clicked.connect(self.accept)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        self.update_preview(self.candidates.currentText())
        self.cancel.setFocus()

    def selected_origin(self):
        return self.candidates.currentText()

    def update_preview(self, value):
        self.preview.setText('将同步为：' + value)
        self.candidates.setToolTip(value)
        self.fit_labels()

    def fit_labels(self):
        for widget, inset in getattr(self, 'wrapped', []):
            widget.setMinimumHeight(max(0, widget.heightForWidth(max(200, self.width() - inset))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_labels()


def choose_origin(parent, proposal):
    dialog = OriginDialog(parent, proposal)
    return dialog.selected_origin() if dialog.exec() == QDialog.Accepted else None
