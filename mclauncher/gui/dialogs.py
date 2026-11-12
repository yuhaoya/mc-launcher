from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ListWidget,
    MessageBoxBase,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from .icons import ProjectIcon
from .theme import palette
from .workers import Worker

RELEASE_LABELS = {"release": "正式版", "beta": "测试版", "alpha": "内测版"}


def short_game_version(version_id: str) -> str:
    """把 ``1.20.1-forge`` / ``1.20.1-Fabric`` 之类收敛成 ``1.20.1``。"""
    text = str(version_id or "").strip()
    if not text:
        return ""
    for sep in ("-", "_", "+", " "):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if head:
                return head
    return text


class VersionPickerDialog(MessageBoxBase):
    """选择要安装的模组/资源包文件。

    左侧列出所有可用文件，第一行是推荐版本并默认选中。
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

        head = QHBoxLayout()
        head.setSpacing(12)
        self.icon = ProjectIcon(48, self)
        self.icon.set_project(project.get("title") or "", str(project.get("icon_url") or ""))
        head.addWidget(self.icon, 0, Qt.AlignTop)

        head_texts = QVBoxLayout()
        head_texts.setSpacing(4)
        self.titleLabel = SubtitleLabel(project.get("title") or "选择版本", self)
        head_texts.addWidget(self.titleLabel)

        meta = f"{project.get('author') or '未知作者'}"
        if game_version:
            meta += f" · 游戏 {short_game_version(game_version)}"
        if loader:
            meta += f" · {loader}"
        self.meta_label = CaptionLabel(meta, self)
        self.meta_label.setTextColor(palette()["secondary"], palette()["secondary"])
        head_texts.addWidget(self.meta_label)
        head.addLayout(head_texts, 1)
        self.viewLayout.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        # 左侧：可用文件列表
        self.list_widget = ListWidget(self)
        self.list_widget.setMinimumWidth(380)
        self.list_widget.setMinimumHeight(340)
        self.list_widget.setSpacing(4)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        body.addWidget(self.list_widget, 1)

        # 右侧：选中项详情
        detail = QWidget(self)
        detail.setFixedWidth(230)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(8)

        self.detail_title = StrongBodyLabel("", detail)
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)

        self.detail_type = CaptionLabel("", detail)
        self.detail_type.setTextColor(palette()["secondary"], palette()["secondary"])
        detail_layout.addWidget(self.detail_type)

        self.detail_game = CaptionLabel("", detail)
        self.detail_game.setTextColor(palette()["secondary"], palette()["secondary"])
        self.detail_game.setWordWrap(True)
        detail_layout.addWidget(self.detail_game)

        self.detail_date = CaptionLabel("", detail)
        self.detail_date.setTextColor(palette()["tertiary"], palette()["tertiary"])
        detail_layout.addWidget(self.detail_date)

        self.detail_file = CaptionLabel("", detail)
        self.detail_file.setTextColor(palette()["tertiary"], palette()["tertiary"])
        self.detail_file.setWordWrap(True)
        detail_layout.addWidget(self.detail_file)

        detail_layout.addStretch(1)
        body.addWidget(detail)

        self.viewLayout.addLayout(body)

        self.status_label = CaptionLabel("正在读取可用版本…", self)
        self.status_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.viewLayout.addWidget(self.status_label)

        self.yesButton.setText("安装选中版本")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        self.widget.setMinimumWidth(760)
        self.widget.setMinimumHeight(520)
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
        self.list_widget.clear()
        if not versions:
            self.status_label.setText("没有找到匹配的文件，换个游戏版本或加载器试试。")
            self.yesButton.setEnabled(False)
            return

        for index, version in enumerate(versions):
            item = self._build_row(version, index)
            self.list_widget.addItem(item)
            widget = getattr(item, "_row_widget", None)
            if widget is not None:
                self.list_widget.setItemWidget(item, widget)

        self.status_label.setText(f"共 {len(versions)} 个文件，第一行为推荐版本。")
        self.list_widget.setCurrentRow(0)
        self.yesButton.setEnabled(True)

    def _build_row(self, version: dict[str, Any], index: int) -> QListWidgetItem:
        name = str(version.get("name") or version.get("version_number") or "未命名")
        item = QListWidgetItem()

        row = QWidget(self.list_widget)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title_text = name
        if version.get("recommended"):
            title_text = f"★ 推荐 · {name}"
        title = StrongBodyLabel(title_text, row)
        if version.get("recommended"):
            font = title.font()
            font.setWeight(QFont.DemiBold)
            title.setFont(font)
            title.setTextColor(QColor("#0F6CBD"), QColor("#4CC2FF"))
        layout.addWidget(title)

        meta_parts = [RELEASE_LABELS.get(str(version.get("release_type")), "正式版")]
        games = list(version.get("game_versions") or [])
        if games:
            meta_parts.append(", ".join(games[:3]) + ("…" if len(games) > 3 else ""))
        date = str(version.get("date_published") or "")[:10]
        if date:
            meta_parts.append(date)
        meta = CaptionLabel(" · ".join(meta_parts), row)
        meta.setTextColor(palette()["secondary"], palette()["secondary"])
        layout.addWidget(meta)

        item.setSizeHint(row.sizeHint())
        item.setData(Qt.UserRole, index)
        # 把控件挂到 item 上，addItem 之后由 caller 设置
        item._row_widget = row  # type: ignore[attr-defined]
        return item

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.versions):
            self.selected_version = None
            self.yesButton.setEnabled(False)
            return
        version = self.versions[row]
        self.selected_version = version
        self.yesButton.setEnabled(True)

        self.detail_title.setText(str(version.get("name") or version.get("version_number") or ""))
        self.detail_type.setText(
            "推荐版本" if version.get("recommended")
            else RELEASE_LABELS.get(str(version.get("release_type")), "正式版")
        )
        games = list(version.get("game_versions") or [])
        self.detail_game.setText("游戏版本：" + (", ".join(games) if games else "—"))
        self.detail_date.setText("发布时间：" + (str(version.get("date_published") or "")[:10] or "—"))
        file_info = version.get("file") or {}
        filename = str(file_info.get("filename") or "")
        size = int(file_info.get("size") or 0)
        if size:
            self.detail_file.setText(f"{filename}\n{size / 1048576:.1f} MB")
        else:
            self.detail_file.setText(filename or "")

    def _on_error(self, message: str) -> None:
        self._failed = True
        self.status_label.setText(f"读取失败：{message}")
        self.yesButton.setEnabled(False)

    def validate(self) -> bool:
        return self.selected_version is not None
