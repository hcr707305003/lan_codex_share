"""Asynchronous external Share observation, separate from owned process lifecycle."""
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .external_share import ExternalState, inspect_share, force_close_share


class ExternalShareMonitor(QObject):
    changed = Signal()
    completed = Signal(str)
    result = Signal(int, str, object)

    def __init__(self, config_path, owned_active, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.owned_active = owned_active
        self.state = ExternalState('checking', '正在检测外部 Share…')
        self.busy = False
        self.scanning = False
        self.closed = False
        self.generation = 0
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.scan)
        self.result.connect(self.finish)

    def start(self):
        self.timer.start()
        self.scan()

    def _job(self, kind, operation):
        generation = self.generation
        def work():
            try:
                value = operation()
            except Exception as exc:
                value = (ExternalState('unknown', '外部 Share 检测失败，请检查权限') if kind == 'scan'
                         else str(exc) if isinstance(exc, ValueError) else '强制关闭失败，请检查权限并重新检测')
            try:
                self.result.emit(generation, kind, value)
            except RuntimeError:
                pass  # The observer window was already destroyed; never touch processes here.
        threading.Thread(target=work, daemon=True).start()

    def scan(self):
        if self.closed or self.busy or self.scanning or self.owned_active():
            return
        self.scanning = True
        self._job('scan', lambda: inspect_share(self.config_path))

    def force_close(self, identity):
        if self.closed or self.busy or self.owned_active() or self.state.identity != identity:
            return False
        self.generation += 1  # An earlier read-only scan must not override a close result.
        self.scanning = False
        self.busy = True
        self.changed.emit()
        self._job('close', lambda: force_close_share(identity))
        return True

    def finish(self, generation, kind, value):
        if self.closed or generation != self.generation:
            return
        if kind == 'scan':
            self.scanning = False
            self.state = value
        else:
            self.busy = False
            self.state = ExternalState('checking', '正在重新检测外部 Share…')
            self.completed.emit(value)
            self.scan()
        self.changed.emit()

    def close(self):
        self.closed = True
        self.generation += 1
        self.timer.stop()
