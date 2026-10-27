from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import Callable, TextIO

from .util import format_eta, format_speed, human_size

ProgressCallback = Callable[[dict], None]


class Progress:
    """线程安全的下载/安装进度条。

    GUI 可以传 ``callback`` 接收结构化进度事件，并传 ``cancel_event``
    让下载线程在下一个数据块处停下。CLI 不传这两个参数时行为不变。
    """

    def __init__(
        self,
        label: str,
        total: int = 0,
        stream: TextIO | None = None,
        width: int = 24,
        enabled: bool = True,
        callback: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ):
        self.label = label
        self.total = max(0, int(total))
        self.done = 0
        self.stream = stream or sys.stdout
        self.width = width
        self.enabled = enabled
        self.callback = callback
        self.cancel_event = cancel_event
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._lock = threading.Lock()
        self._start = time.time()
        self._last_render = 0.0
        self._last_notify = 0.0
        self._speed = 0.0
        self._samples: deque[tuple[float, int]] = deque(maxlen=20)
        self._finished = False
        self._rendered = False
        if self.enabled and self.total:
            self._render(force=True)
        self._notify(force=True)

    # ------------------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return bool(self.cancel_event is not None and self.cancel_event.is_set())

    @property
    def percent(self) -> float:
        return min(100.0, self.done * 100.0 / self.total) if self.total else 0.0

    def add_total(self, amount: int) -> None:
        with self._lock:
            self.total += max(0, amount)
        self._notify(force=True)

    def advance(self, amount: int) -> None:
        if not amount:
            return
        with self._lock:
            self.done = max(0, self.done + amount)
            self._samples.append((time.time(), self.done))
        if self.enabled or self.callback is not None:
            self._notify()

    def _speed_now(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        t0, b0 = self._samples[0]
        t1, b1 = self._samples[-1]
        dt = t1 - t0
        if dt <= 0:
            return 0.0
        return max(0.0, (b1 - b0) / dt)

    def _render(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.time()
        if not force and now - self._last_render < 0.1:
            return
        self._last_render = now
        self._speed = self._speed_now() or self._speed
        if self.total:
            ratio = min(1.0, self.done / self.total)
            filled = int(self.width * ratio)
            bar = "#" * filled + "-" * (self.width - filled)
            pct = f"{ratio * 100:5.1f}%"
            body = (
                f"{self.label}  [{bar}] {pct}  "
                f"{human_size(self.done)}/{human_size(self.total)}  "
                f"{format_speed(self._speed)}  ETA {format_eta((self.total - self.done) / self._speed if self._speed > 0 else None)}"
            )
        else:
            spinner = "|/-\\"[int(now * 4) % 4]
            body = f"{self.label}  {spinner}  {human_size(self.done)}  {format_speed(self._speed)}"
        if self.is_tty:
            self.stream.write("\r\x1b[K" + body)
        else:
            self.stream.write(body + "\n")
        self.stream.flush()
        self._rendered = True

    def _notify(self, force: bool = False) -> None:
        self._render(force=force)
        if self.callback is None:
            return
        now = time.time()
        if not force and now - self._last_notify < 0.12:
            return
        self._last_notify = now
        self._speed = self._speed_now() or self._speed
        try:
            self.callback(
                {
                    "label": self.label,
                    "done": self.done,
                    "total": self.total,
                    "percent": self.percent,
                    "speed": self._speed,
                    "finished": self._finished,
                }
            )
        except Exception:
            # 进度回调不能影响下载本身
            pass

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self.enabled:
            with self._lock:
                if self.total and self.done != self.total:
                    self.done = self.total
                self._render(force=True)
                if self.is_tty:
                    self.stream.write("\n")
                self.stream.flush()
        self._notify(force=True)
