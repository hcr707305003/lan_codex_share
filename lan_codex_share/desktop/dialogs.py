"""Service confirmation presentation only; callers own all lifecycle actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QLayout, QScrollArea, QSizePolicy
from .icons import decorate, app_icon


class StopDialog(QDialog):
    def __init__(self, parent, service, *, force=False, details='', exiting=False):
        super().__init__(parent)
        self.setObjectName('stopDialog')
        self.setWindowIcon(app_icon())
        self.setWindowTitle(f'{"强制关闭" if force else "停止"} {service}')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(420)
        self.resize(520, 390)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        eyebrow = QLabel()
        eyebrow.setFixedSize(28, 28)
        decorate(eyebrow, 'warning', 'danger')
        layout.addWidget(eyebrow)
        title = QLabel('停止服务并退出？' if exiting else f'{"强制关闭" if force else "停止"} {service}？')
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setObjectName('heading')
        self.title_label = title
        layout.addWidget(title)
        message = ('强制关闭可能中断正在执行的任务，并跳过正常清理。仅处理已经验证归属的进程。' if force else
                   '将停止本客户端启动的服务并取消下载。正在使用的连接或任务可能中断，外部服务保持运行。' if exiting else
                   '正在使用此服务的连接或任务可能中断。其他服务不会联动停止。')
        body = QLabel(message)
        body.setObjectName('muted')
        body.setWordWrap(True)
        self.body_label = body
        layout.addWidget(body)
        panel = QFrame()
        panel.setObjectName('panel')
        content = QVBoxLayout(panel)
        content.setContentsMargins(14, 12, 14, 12)
        self.detail = QLabel(details or f'目标服务：{service}')
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        content.addWidget(self.detail)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(80)
        scroll.setMaximumHeight(200)
        scroll.setWidget(panel)
        layout.addWidget(scroll, 1)
        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        self.cancel = QPushButton('取消')
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        self.confirm = QPushButton('停止并退出' if exiting else '强制关闭' if force else '停止服务')
        self.confirm.setObjectName('danger')
        self.confirm.setAutoDefault(False)
        self.confirm.setDefault(False)
        self.confirm.clicked.connect(self.accept)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        self.cancel.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Wrapped labels must not shrink vertically when the details grow.
        if hasattr(self, 'detail'):
            for widget, inset in ((self.title_label, 52), (self.body_label, 52), (self.detail, 96)):
                widget.setMinimumHeight(max(0, widget.heightForWidth(max(200, self.width() - inset))))


def confirm_stop(parent, service, **options):
    return StopDialog(parent, service, **options).exec() == QDialog.Accepted
