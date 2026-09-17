"""Per-configuration-directory appearance preferences; never restarts services."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                              QPushButton, QLabel, QWidget, QScrollArea)
from .theme import THEMES, apply_theme, normalize_theme
from .icons import app_icon


class ThemeButton(QPushButton):
    def __init__(self, theme_id, parent=None):
        super().__init__(parent)
        self.theme_id = theme_id
        self.setObjectName('themeChoice')
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setAccessibleName(THEMES[theme_id].name)
        self.setToolTip(THEMES[theme_id].description)
        self.setMinimumSize(210, 144)

    def sizeHint(self):
        return QSize(260, 150)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = THEMES[self.theme_id].colors
        painter.setPen(Qt.NoPen)
        rect = QRectF(14, 14, self.width() - 28, 68)
        painter.setBrush(QColor(c['bg']))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setBrush(QColor(c['soft']))
        painter.drawRoundedRect(QRectF(22, 22, 35, 52), 3, 3)
        painter.setBrush(QColor(c['text']))
        painter.drawRoundedRect(QRectF(65, 24, 60, 4), 2, 2)
        width = (self.width() - 95) / 3
        for i in range(3):
            painter.setBrush(QColor(c['card']))
            painter.drawRoundedRect(QRectF(65 + i * (width + 5), 36, width, 38), 3, 3)
        painter.setBrush(QColor(c['accent']))
        painter.drawRoundedRect(QRectF(65 + 2 * (width + 5), 66, width, 8), 2, 2)
        current = THEMES[normalize_theme(QApplication.instance().property('theme_id'))].colors
        painter.setPen(QColor(current['text']))
        painter.drawText(QRectF(15, 89, self.width() - 30, 24), Qt.AlignLeft, THEMES[self.theme_id].name)
        painter.setPen(QColor(current['muted']))
        font = painter.font()
        font.setPointSizeF(max(8, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.drawText(QRectF(15, 114, self.width() - 30, 23), Qt.AlignLeft, THEMES[self.theme_id].description)


class AppearanceDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('外观设置')
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(640, 530)
        self.setMinimumWidth(510)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        title = QLabel('外观设置')
        title.setObjectName('title')
        layout.addWidget(title)
        note = QLabel('选择适合你的风格。页面、表单、日志和弹窗统一切换。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.theme_buttons = {}
        for index, theme_id in enumerate(THEMES):
            button = ThemeButton(theme_id)
            button.clicked.connect(lambda checked=False, key=theme_id: self.select_theme(key))
            grid.addWidget(button, index // 2, index % 2)
            self.theme_buttons[theme_id] = button
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.message = QLabel('选择后自动保存；只修改本机界面偏好，不影响服务配置。')
        self.message.setObjectName('muted')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        hint = QLabel('统一应用图标不随主题改变')
        hint.setObjectName('caption')
        row.addWidget(hint, 1)
        done = QPushButton('完成')
        done.setObjectName('primary')
        done.setDefault(True)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        layout.addLayout(row)
        self._selected = normalize_theme(QApplication.instance().property('theme_id'))
        self.update_selection()

    def update_selection(self):
        for key, button in self.theme_buttons.items():
            button.setChecked(key == self._selected)
            button.update()

    def select_theme(self, theme_id):
        theme_id = normalize_theme(theme_id)
        try:
            self.settings.save({'theme': theme_id})
        except (OSError, ValueError):
            self.message.setText('外观保存失败，请检查桌面配置文件和目录权限。已保留原主题。')
            self.update_selection()
            return False
        self._selected = apply_theme(QApplication.instance(), theme_id)
        self.update_selection()
        self.message.setText('已保存 · ' + THEMES[theme_id].name + '。下次打开客户端将继续使用。')
        return True
