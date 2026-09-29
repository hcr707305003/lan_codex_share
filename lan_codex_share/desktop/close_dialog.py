"""Close-window choices; lifecycle actions remain in DesktopWindow."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from .icons import app_icon


class CloseDialog(QDialog):
    BACKGROUND = 2
    DETACH = 3

    def __init__(self, parent, tray_available):
        super().__init__(parent)
        self.setWindowTitle('关闭控制台')
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        heading = QLabel('关闭窗口后，服务如何处理？')
        heading.setObjectName('heading')
        layout.addWidget(heading)
        body = QLabel('后台运行会隐藏到系统托盘，保留服务、日志和未保存的配置。\n'
                      '仅退出控制台会关闭窗口和托盘，服务及独立日志继续运行。\n'
                      '停止并退出只处理本客户端启动的服务，外部服务不受影响。')
        body.setWordWrap(True)
        body.setObjectName('muted')
        layout.addWidget(body)
        self.background = QPushButton('后台运行 · 保留服务')
        self.background.setObjectName('primary')
        self.background.setEnabled(tray_available)
        self.background.clicked.connect(lambda: self.done(self.BACKGROUND))
        layout.addWidget(self.background)
        if not tray_available:
            note = QLabel('当前系统没有可用托盘，无法隐藏窗口；可取消并最小化。')
            note.setWordWrap(True)
            layout.addWidget(note)
        self.detach = QPushButton('仅退出控制台 · 保留服务')
        self.detach.clicked.connect(lambda: self.done(self.DETACH))
        layout.addWidget(self.detach)
        self.stop = QPushButton('停止本客户端服务并退出…')
        self.stop.setObjectName('danger')
        self.stop.clicked.connect(self.accept)
        layout.addWidget(self.stop)
        self.cancel = QPushButton('取消')
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)
        for button in (self.background, self.detach, self.stop):
            button.setAutoDefault(False)
        self.cancel.setDefault(True)
        self.cancel.setFocus()
