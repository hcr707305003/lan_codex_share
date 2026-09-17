"""Background tunnel observation and explicitly confirmed external FRP close."""
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .external_tunnels import TunnelState, inspect_tunnels, close_external_frpc


class ExternalTunnelMonitor(QObject):
    changed = Signal()
    result = Signal(int, str, object)
    completed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.states = {n: TunnelState('checking', '正在检测外部隧道…') for n in ('frpc', 'Tunnel')}
        self.scanning = False
        self.closed = False
        self.busy = False
        self.generation = 0
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.scan)
        self.result.connect(self.finish)

    def start(self):
        self.timer.start()
        self.scan()

    def scan(self):
        if self.closed or self.scanning or self.busy:
            return
        self.scanning = True
        generation = self.generation
        def work():
            try:
                states = inspect_tunnels(self.settings)
            except Exception:
                states = {n: TunnelState('unknown', '外部隧道检测失败，请检查权限或配置') for n in self.states}
            try:
                self.result.emit(generation, 'scan', states)
            except RuntimeError:
                pass  # The Qt window was destroyed while this read-only job ran.
        threading.Thread(target=work, daemon=True).start()

    def close_frpc(self, identity):
        if self.closed or self.busy or identity is None or self.states['frpc'].identity != identity:
            return False
        self.generation += 1
        generation = self.generation
        self.scanning = False
        self.busy = True
        self.changed.emit()
        def work():
            try:
                message = close_external_frpc(self.settings, identity)
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else '关闭外部 FRP 失败，请检查权限并重新检测'
            try:
                self.result.emit(generation, 'close', message)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()
        return True

    def finish(self, generation, kind, value):
        if self.closed or generation != self.generation:
            return
        if kind == 'scan':
            self.scanning = False
            self.states = value
        else:
            self.busy = False
            self.states['frpc'] = TunnelState('checking', '正在重新检测外部 FRP…')
            self.completed.emit(value)
            self.scan()
        self.changed.emit()

    def close(self):
        self.closed = True
        self.generation += 1
        self.scanning = False
        self.timer.stop()
