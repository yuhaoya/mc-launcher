from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidgetItem
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from .theme import palette
from .workers import Worker

RELEASE_LABELS = {"release": "正式版", "beta": "测试版", "alpha": "内测版"}


class VersionPickerDialog(MessageBoxBase):
    """选择要安装的模组/资源包文件版本。

    第一行是推荐版本（默认选中），其余按正式版优先、时间倒序排列。
    """

    def __init__(
        self,
        project: dict[str, Any],
        game_version: str | None,
        loader: str | None,
        service,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.project = project
        self.game_version = game_version
        self.loader = loader
        self.selected_version: dict[str, Any] | None = None
        self.versions: list[dict[str, Any]] = []
        self._worker: Worker | None = None
        self._failed = False

        self.titleLabel = SubtitleLabel(project.get("title") or "选择版本", self)
        self.viewLayout.addWidget(self.titleLabel)

        meta = f"{project.get('author') or '未知作者'}"
        if game_version:
            meta += f" · 游戏 {game_version}"
        if loader:
            meta += f" · {loader}"
        self.meta_label = CaptionLabel(meta, self)
        self.meta_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.viewLayout.addWidget(self.meta_label)

        self.table = TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["版本", "类型", "游戏版本", "发布时间"])
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(320)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 84), (2, 150), (3, 104)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.viewLayout.addWidget(self.table)

        self.status_label = CaptionLabel("正在读取可用版本…", self)
        self.status_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.viewLayout.addWidget(self.status_label)

        self.yesButton.setText("安装")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        self.widget.setMinimumWidth(680)
        self._load()

    def exec(self) -> int:  # type: ignore[override]
        """先等版本列表加载完成再显示，避免打开时是一片空白。"""
        if self._worker is not None and not self.versions and not self._failed:
            self._wait_until_loaded()
        return super().exec()

    def _wait_until_loaded(self, timeout_ms: int = 15000) -> None:
        from PySide6.QtCore import QDeadlineTimer, QEventLoop, QTimer

        loop = QEventLoop()
        deadline = QDeadlineTimer(timeout_ms)
        timer = QTimer()
        timer.setInterval(60)

        def poll() -> None:
            if self.versions or self._failed or deadline.hasExpired():
                timer.stop()
                loop.quit()

        timer.timeout.connect(poll)
        timer.start()
        loop.exec()
        timer.stop()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        project_id = str(self.project.get("id") or "")
        worker = Worker(
            lambda w: self.service.content_versions(
                project_id,
                project_type=str(self.project.get("project_type") or "mod"),
                game_version=self.game_version,
                loader=self.loader,
                source=self.project.get("source"),
            )
        )
        worker.signals.result.connect(self._on_loaded)
        worker.signals.error.connect(self._on_error)
        self._worker = worker
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _on_loaded(self, versions: list[dict[str, Any]]) -> None:
        self.versions = versions
        self.table.setRowCount(0)
        if not versions:
            self.status_label.setText("没有找到匹配的文件，试试切换游戏版本或加载器。")
            self.yesButton.setEnabled(False)
            return

        self.table.setRowCount(len(versions))
        for row, version in enumerate(versions):
            label = str(version.get("name") or version.get("version_number") or "")
            if version.get("recommended"):
                label = f"{label}   ★ 推荐"
            name_item = QTableWidgetItem(label)
            if version.get("recommended"):
                font = name_item.font()
                font.setWeight(QFont.DemiBold)
                name_item.setFont(font)
                color = QColor("#0F6CBD")
                name_item.setForeground(color)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(
                row, 1, QTableWidgetItem(RELEASE_LABELS.get(str(version.get("release_type")), "正式版"))
            )
            self.table.setItem(
                row, 2, QTableWidgetItem(", ".join(version.get("game_versions") or []) or "—")
            )
            self.table.setItem(
                row, 3, QTableWidgetItem(str(version.get("date_published") or "")[:10] or "—")
            )

        self.status_label.setText(f"共 {len(versions)} 个可用文件，默认已选中推荐版本。")
        self.table.selectRow(0)
        self.yesButton.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self._failed = True
        self.status_label.setText(f"读取失败：{message}")
        self.yesButton.setEnabled(False)

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self.selected_version = None
            self.yesButton.setEnabled(False)
            return
        index = rows[0].row()
        if 0 <= index < len(self.versions):
            self.selected_version = self.versions[index]
            self.yesButton.setEnabled(True)

    def validate(self) -> bool:
        return self.selected_version is not None
