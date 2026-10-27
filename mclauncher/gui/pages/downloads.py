from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SmoothScrollArea,
    SimpleCardWidget,
    StrongBodyLabel,
    TitleLabel,
    TransparentToolButton,
)

from ...services import LauncherService
from ...util import format_eta, format_speed, human_size
from ..theme import palette
from ..widgets import EmptyState


class TaskCard(SimpleCardWidget):
    cancelRequested = Signal(str)

    def __init__(self, task_id: str, version_id: str, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.version_id = version_id
        self.state = "running"
        self.setMinimumHeight(112)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 18, 14)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(10)
        icon = IconWidget(FluentIcon.DOWNLOAD, self)
        icon.setFixedSize(20, 20)
        top.addWidget(icon)
        self.title_label = StrongBodyLabel(f"Minecraft {version_id}", self)
        top.addWidget(self.title_label)
        self.status_label = CaptionLabel("准备中…", self)
        self.status_label.setTextColor(palette()["secondary"], palette()["secondary"])
        top.addWidget(self.status_label)
        top.addStretch(1)
        self.cancel_button = TransparentToolButton(self)
        self.cancel_button.setIcon(FluentIcon.CLOSE)
        self.cancel_button.setToolTip("取消安装")
        self.cancel_button.clicked.connect(lambda: self.cancelRequested.emit(self.task_id))
        top.addWidget(self.cancel_button)
        layout.addLayout(top)

        self.progress = ProgressBar(self)
        self.progress.setValue(0)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.phase_label = CaptionLabel("等待开始", self)
        self.phase_label.setTextColor(palette()["secondary"], palette()["secondary"])
        bottom.addWidget(self.phase_label, 1)
        self.metrics_label = CaptionLabel("", self)
        self.metrics_label.setTextColor(palette()["tertiary"], palette()["tertiary"])
        bottom.addWidget(self.metrics_label, 0, Qt.AlignRight)
        layout.addLayout(bottom)

    def update_progress(self, event: dict) -> None:
        if self.state != "running":
            return
        percent = float(event.get("percent") or 0)
        self.progress.setValue(int(percent))
        label = str(event.get("label") or "下载")
        self.phase_label.setText(label)
        done = int(event.get("done") or 0)
        total = int(event.get("total") or 0)
        speed = float(event.get("speed") or 0)
        if total:
            eta = format_eta((total - done) / speed if speed > 0 else None)
            self.metrics_label.setText(
                f"{human_size(done)} / {human_size(total)}   {format_speed(speed)}   ETA {eta}"
            )
        else:
            self.metrics_label.setText(format_speed(speed) if speed else "")
        self.status_label.setText(f"{percent:.0f}%")

    def set_log(self, message: str) -> None:
        if not message:
            return
        first = message.strip().splitlines()[0] if message.strip() else ""
        if first.startswith("[*]"):
            text = first[3:].strip()
            if text:
                self.phase_label.setText(text[:90])

    def set_done(self, message: str = "安装完成") -> None:
        self.state = "done"
        self.progress.setValue(100)
        self.status_label.setText("完成")
        self.phase_label.setText(message)
        self.metrics_label.setText("")
        self.cancel_button.hide()
        self.progress.setCustomBackgroundColor("#6CCB5F", "#6CCB5F") if hasattr(
            self.progress, "setCustomBackgroundColor"
        ) else None

    def set_error(self, message: str) -> None:
        self.state = "error"
        self.status_label.setText("失败")
        self.phase_label.setText(message[:120])
        self.metrics_label.setText("")
        self.cancel_button.hide()

    def set_cancelled(self) -> None:
        self.state = "cancelled"
        self.status_label.setText("已取消")
        self.phase_label.setText("安装已取消，可以重新尝试。")
        self.metrics_label.setText("")
        self.cancel_button.hide()


class DownloadsPage(QWidget):
    cancelRequested = Signal(str)

    def __init__(self, service: LauncherService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("downloadsPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#downloadsPage {{ background: transparent; }}")
        self._cards: dict[str, TaskCard] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("下载", self)
        title.setStyleSheet("font-size: 26px; font-weight: 600;")
        titles.addWidget(title)
        subtitle = QLabel("安装进度、阶段与日志都会显示在这里。", self)
        subtitle.setStyleSheet(f"color: {palette()['secondary']}; font-size: 10pt;")
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.clear_button = PushButton(self)
        self.clear_button.setText("清理已完成")
        self.clear_button.setIcon(FluentIcon.BROOM)
        self.clear_button.clicked.connect(self.clear_finished)
        header.addWidget(self.clear_button, 0, Qt.AlignBottom)
        outer.addLayout(header)

        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(container)
        self.cards_layout.setContentsMargins(0, 0, 8, 0)
        self.cards_layout.setSpacing(10)
        self.empty = EmptyState(
            FluentIcon.DOWNLOAD,
            "暂无下载任务",
            "在「版本」页选择版本并点击安装，任务会出现在这里。",
            container,
        )
        self.cards_layout.addWidget(self.empty)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(container)
        outer.addWidget(self.scroll, 1)

        log_header = QHBoxLayout()
        log_title = StrongBodyLabel("安装日志", self)
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        self.log_hint = CaptionLabel("只保留最近一次任务输出", self)
        self.log_hint.setTextColor(palette()["tertiary"], palette()["tertiary"])
        log_header.addWidget(self.log_hint)
        outer.addLayout(log_header)
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setFixedHeight(150)
        self.log.setFont(QFont("Cascadia Mono" if hasattr(QFont, "Cascadia Mono") else "Consolas", 9))
        self.log.setPlaceholderText("安装日志会显示在这里…")
        self.log.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {palette()["card_alt"]}; color: {palette()["secondary"]};
                border: 1px solid {palette()["border"]}; border-radius: 8px; padding: 8px;
            }}
            """
        )
        outer.addWidget(self.log)

    # ------------------------------------------------------------------
    def add_task(self, task_id: str, version_id: str) -> TaskCard:
        card = TaskCard(task_id, version_id, self.scroll.widget())
        card.cancelRequested.connect(self.cancelRequested.emit)
        self._cards[task_id] = card
        if self.empty.isVisible() or self.empty.parent() is not None:
            self.empty.hide()
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.log.clear()
        self.append_log(f"[*] 创建安装任务：Minecraft {version_id}")
        return card

    def card(self, task_id: str) -> TaskCard | None:
        return self._cards.get(task_id)

    def update_progress(self, task_id: str, event: dict) -> None:
        card = self._cards.get(task_id)
        if card:
            card.update_progress(event)

    def append_log(self, message: str) -> None:
        if message:
            self.log.appendPlainText(message)
            card = next((c for c in self._cards.values() if c.state == "running"), None)
            if card:
                card.set_log(message)

    def finish_task(self, task_id: str, ok: bool, message: str) -> None:
        card = self._cards.get(task_id)
        if not card:
            return
        cancelled = "取消" in message
        if ok:
            card.set_done("安装完成")
            self.append_log(f"[+] Minecraft {card.version_id} 安装完成")
        elif cancelled:
            card.set_cancelled()
            self.append_log(f"[!] 已取消：Minecraft {card.version_id}")
        else:
            card.set_error(message)
            self.append_log(f"[!] 安装失败：{message}")
        self._update_empty()

    def clear_finished(self) -> None:
        for task_id, card in list(self._cards.items()):
            if card.state != "running":
                card.deleteLater()
                del self._cards[task_id]
        self.log.clear()
        self._update_empty()

    def _update_empty(self) -> None:
        has_visible = any(card.state == "running" for card in self._cards.values()) or any(
            not card.isHidden() for card in self._cards.values()
        )
        self.empty.setVisible(not bool(self._cards))

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"QWidget#downloadsPage {{ background: {palette()['bg']}; }}")
        self.log.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {palette()["card_alt"]}; color: {palette()["secondary"]};
                border: 1px solid {palette()["border"]}; border-radius: 8px; padding: 8px;
            }}
            """
        )
