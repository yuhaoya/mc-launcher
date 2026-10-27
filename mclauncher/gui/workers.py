from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(dict)
    log = Signal(str)
    started = Signal(int)
    code = Signal(dict)
    status = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    """把阻塞的启动器操作放到全局线程池，所有 UI 更新通过信号回到主线程。"""

    def __init__(self, fn: Callable[["Worker"], Any]):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            value = self.fn(self)
        except Exception as exc:
            self._emit(self.signals.error, str(exc) or exc.__class__.__name__)
        else:
            self._emit(self.signals.result, value)
        finally:
            self._emit(self.signals.finished)

    @staticmethod
    def _emit(signal, *args: Any) -> None:
        # 窗口关闭时 QObject 可能已经被销毁，忽略这类竞态即可。
        try:
            signal.emit(*args)
        except RuntimeError:
            pass
