from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import sys

from .. import __version__


def distribution_directory():
    if not getattr(sys, 'frozen', False):
        return Path(__file__).resolve().parents[2]
    executable = Path(sys.executable).resolve()
    if sys.platform == 'darwin' and executable.parent.name == 'MacOS' and executable.parent.parent.name == 'Contents':
        return executable.parents[3]
    return executable.parent


@contextmanager
def console_interrupts(window):
    """Dispatch Ctrl+C through Qt close handling, never inside a signal handler."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    pending = False
    closing = False

    def interrupt(signum, frame):
        nonlocal pending
        if not closing:
            pending = True

    def poll():
        nonlocal pending, closing
        if not pending or closing or QApplication.activeModalWidget() is not None:
            return
        pending = False
        if window.exiting:
            return
        closing = True
        try:
            window.close()
        finally:
            closing = False

    timer = QTimer()
    timer.timeout.connect(poll)
    previous = signal.signal(signal.SIGINT, interrupt)
    try:
        timer.start(100)
        yield
    finally:
        timer.stop()
        signal.signal(signal.SIGINT, previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description='LAN Codex Share 桌面服务控制台')
    parser.add_argument('--config', help='LAN 配置路径，默认读取程序同目录 lan_config.toml')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    path = Path(args.config).expanduser().resolve() if args.config else distribution_directory() / 'lan_config.toml'
    if args.smoke_test:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        from .messages import MessageBox as QMessageBox
        from .window import DesktopWindow
        from .theme import apply_theme
        from .icons import app_icon
    except ImportError as exc:
        message = '桌面依赖无法加载。请使用独立 CPython 虚拟环境安装 requirements-desktop.txt，或使用已打包客户端。'
        try:
            error_file = path.parent / 'runtime' / 'desktop' / 'startup-error.log'
            error_file.parent.mkdir(parents=True, exist_ok=True)
            error_file.write_text(f'{type(exc).__name__}: {exc}\n', encoding='utf-8')
            message += f'\n诊断信息：{error_file}'
        except OSError:
            pass
        if sys.stderr:
            print(message, file=sys.stderr)
        elif os.name == 'nt' and not args.smoke_test:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'LAN Codex Share 启动失败', 0x10)
        return 2
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('LAN Codex Share')
    app.setStyle('Fusion')
    font = QFont()
    font.setFamilies(['Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC', 'Segoe UI', 'sans-serif'])
    font.setPointSize(10)
    app.setFont(font)
    app.setWindowIcon(app_icon())
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('org.lancodexshare.desktop')
    apply_theme(app, 'graphite')
    try:
        window = DesktopWindow(path)
    except (OSError, ValueError):
        QMessageBox.critical(None, '客户端启动失败', '桌面配置不可读或运行目录不可写，请检查所选配置目录。')
        return 2
    with console_interrupts(window):
        window.show()
        if args.smoke_test:
            QTimer.singleShot(300, window.close)
        return app.exec()
