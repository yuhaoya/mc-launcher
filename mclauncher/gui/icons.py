from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel

from ..paths import default_config_dir
from .theme import accent_color

_ICON_SIZE = 48


def _cache_dir() -> Path:
    path = default_config_dir() / "cache" / "icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(url: str, size: int) -> Path:
    digest = hashlib.sha1(f"{url}|{size}".encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.png"


class IconLoader(QObject):
    """异步下载项目图标，带磁盘缓存。

    Modrinth 的 icon_url 指向 CDN，需要联网获取；直接用 QLabel 显示 URL
    是不生效的，这也是之前头像处只显示占位方块的原因。
    """

    _instance: IconLoader | None = None

    loaded = Signal(str, QPixmap)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._pending: dict[str, list[QLabel]] = {}
        self._memory: dict[str, QPixmap] = {}
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "IconLoader":
        if cls._instance is None:
            cls._instance = IconLoader()
        return cls._instance

    def cached(self, url: str, size: int) -> QPixmap | None:
        key = f"{url}|{size}"
        pixmap = self._memory.get(key)
        if pixmap is not None and not pixmap.isNull():
            return pixmap
        path = _cache_path(url, size)
        if path.is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._memory[key] = pixmap
                return pixmap
        return None

    def request(self, url: str, size: int, on_ready) -> QPixmap | None:
        """返回缓存图；没有缓存时发起下载，完成后回调 (url, pixmap)。"""
        if not url:
            return None
        pixmap = self.cached(url, size)
        if pixmap is not None:
            return pixmap

        key = f"{url}|{size}"
        with self._lock:
            if key in self._pending:
                return None
            self._pending[key] = []

        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "MicalithLauncher/1.0")
        reply = self._manager.get(request)
        reply.finished.connect(lambda: self._on_finished(reply, url, size, on_ready))
        return None

    def _on_finished(self, reply: QNetworkReply, url: str, size: int, on_ready) -> None:
        key = f"{url}|{size}"
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = bytes(reply.readAll().data())
                pixmap = QPixmap()
                if data and pixmap.loadFromData(data):
                    scaled = pixmap.scaled(
                        QSize(size, size),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._memory[key] = scaled
                    try:
                        scaled.save(str(_cache_path(url, size)), "PNG")
                    except OSError:
                        pass
                    try:
                        on_ready(url, scaled)
                    except RuntimeError:
                        pass
        finally:
            reply.deleteLater()
            with self._lock:
                self._pending.pop(key, None)


class ProjectIcon(QLabel):
    """方形圆角图标：先显示首字母占位，加载成功后替换为真实图标。"""

    def __init__(self, size: int = _ICON_SIZE, parent=None):
        super().__init__(parent)
        self._size = size
        self._url = ""
        self._fallback_text = "?"
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)

    def set_project(self, title: str, icon_url: str) -> None:
        self._url = icon_url or ""
        self._fallback_text = (title or "?").strip()[:1].upper() or "?"
        pixmap = None
        if self._url:
            pixmap = IconLoader.instance().request(self._url, self._size, self._apply_remote)
        if pixmap is not None:
            self.setPixmap(self._rounded(pixmap))
        else:
            self.setText(self._fallback_text)

    def _apply_remote(self, url: str, pixmap: QPixmap) -> None:
        if url != self._url:
            return
        self.setText("")
        self.setPixmap(self._rounded(pixmap))

    def _rounded(self, pixmap: QPixmap) -> QPixmap:
        target = QPixmap(self._size, self._size)
        target.fill(Qt.GlobalColor.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._size, self._size), 10, 10)
        painter.setClipPath(path)
        scaled = pixmap.scaled(
            self._size,
            self._size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        return target

    def paintEvent(self, event) -> None:
        if not self.pixmap() or self.pixmap().isNull():
            # 没有图标时画一个渐变底 + 首字母，比空白方块好看
            accent = accent_color()
            top = QColor(accent)
            h, s, v, a = top.getHsvF()
            top.setHsvF(h, max(0.0, s * 0.75), min(1.0, v + 0.25), a)

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            gradient = QLinearGradient(0, 0, self._size, self._size)
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, accent)
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(0, 0, self._size, self._size), 10, 10)
            painter.setPen(QColor("#FFFFFF"))
            font = painter.font()
            font.setPixelSize(int(self._size * 0.44))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._fallback_text)
            painter.end()
            return
        super().paintEvent(event)
