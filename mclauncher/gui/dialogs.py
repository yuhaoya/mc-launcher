from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ListWidget,
    MessageBoxBase,
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


def version_group(version_id: str) -> str:
    """分组键：``1.20.1`` -> ``1.20``，``26.3`` -> ``26``。"""
    parts = short_game_version(version_id).split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0] if parts else "其它"


def _version_sort_key(version_id: str) -> tuple:
    """把 1.21.11 拆成数字元组，保证 11 > 9 而不是字符串比较。"""
    chunks = []
    for piece in short_game_version(version_id).split("."):
        chunks.append(int(piece) if piece.isdigit() else 0)
    return tuple(chunks)


class VersionPickerDialog(MessageBoxBase):
    """选择要安装的模组/资源包文件。

    左侧按游戏版本折叠列出可用版本，右侧是该版本下的文件列表，
    第一行为推荐版本并默认选中。
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
        self.game_version = short_game_version(game_version or "")
        self.loader = loader
        self.selected_version: dict[str, Any] | None = None
        self.all_versions: list[dict[str, Any]] = []
        self.versions: list[dict[str, Any]] = []
        self._worker: Worker | None = None
        self._failed = False
        self._loading_group = False

        # 头部
        head = QHBoxLayout()
        head.setSpacing(12)
        self.icon = ProjectIcon(48, self)
        self.icon.set_project(project.get("title") or "", str(project.get("icon_url") or ""))
        head.addWidget(self.icon, 0, Qt.AlignTop)

        head_texts = QVBoxLayout()
        head_texts.setSpacing(4)
        self.titleLabel = SubtitleLabel(project.get("title") or "选择版本", self)
        head_texts.addWidget(self.titleLabel)

        meta = str(project.get("author") or "未知作者")
        if self.game_version:
            meta += f" · 游戏 {self.game_version}"
        if loader:
            meta += f" · {loader}"
        self.meta_label = CaptionLabel(meta, self)
        self.meta_label.setTextColor(palette()["secondary"], palette()["secondary"])
        head_texts.addWidget(self.meta_label)
        head.addLayout(head_texts, 1)
        self.viewLayout.addLayout(head)

        # 主体：左游戏版本树 / 右文件列表
        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        left_title = StrongBodyLabel("游戏版本", self)
        left.addWidget(left_title)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(200)
        self.tree.setMinimumHeight(360)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        left.addWidget(self.tree, 1)
        body.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.file_title = StrongBodyLabel("可用文件", self)
        right.addWidget(self.file_title)
        self.list_widget = ListWidget(self)
        self.list_widget.setMinimumWidth(380)
        self.list_widget.setMinimumHeight(360)
        self.list_widget.setSpacing(4)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        right.addWidget(self.list_widget, 1)
        body.addLayout(right, 1)

        self.viewLayout.addLayout(body)

        self.status_label = CaptionLabel("正在读取可用版本…", self)
        self.status_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.viewLayout.addWidget(self.status_label)

        self.yesButton.setText("安装选中版本")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        self.widget.setMinimumWidth(820)
        self.widget.setMinimumHeight(540)
        self._load()

    # ------------------------------------------------------------------
    def exec(self) -> int:  # type: ignore[override]
        if self._worker is not None and not self.all_versions and not self._failed:
            self._wait_until_loaded()
        return super().exec()

    def _wait_until_loaded(self, timeout_ms: int = 15000) -> None:
        from PySide6.QtCore import QDeadlineTimer, QEventLoop, QTimer

        loop = QEventLoop()
        deadline = QDeadlineTimer(timeout_ms)
        timer = QTimer()
        timer.setInterval(60)

        def poll() -> None:
            if self.all_versions or self._failed or deadline.hasExpired():
                timer.stop()
                loop.quit()

        timer.timeout.connect(poll)
        timer.start()
        loop.exec()
        timer.stop()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        project_id = str(self.project.get("id") or "")
        # 不带版本过滤，一次取全，交给左侧树分组
        worker = Worker(
            lambda w: self.service.content_versions(
                project_id,
                project_type=str(self.project.get("project_type") or "mod"),
                game_version=None,
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
        self.all_versions = versions
        if not versions:
            self.status_label.setText("没有找到可用文件，换个加载器或内容源试试。")
            self.yesButton.setEnabled(False)
            return

        # 按游戏版本建树
        buckets: dict[str, list[dict[str, Any]]] = {}
        for version in versions:
            games = [short_game_version(g) for g in version.get("game_versions") or []]
            if not games:
                games = ["未知"]
            for game in games:
                buckets.setdefault(game, []).append(version)

        self.tree.clear()
        groups: dict[str, list[str]] = {}
        for game in buckets:
            groups.setdefault(version_group(game), []).append(game)

        target_item: QTreeWidgetItem | None = None
        for group in sorted(groups, key=_version_sort_key, reverse=True):
            members = sorted(groups[group], key=_version_sort_key, reverse=True)
            parent = QTreeWidgetItem(self.tree, [f"{group}.x（{len(members)}）"])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            for game in members:
                child = QTreeWidgetItem(parent, [game])
                child.setData(0, Qt.UserRole, game)
                child.setToolTip(0, f"{len(buckets[game])} 个可用文件")
                if game == self.game_version:
                    target_item = child

            expanded = self.game_version and version_group(self.game_version) == group
            parent.setExpanded(bool(expanded) or (target_item is None and group == max(groups, key=_version_sort_key)))

        if target_item is not None:
            self.tree.setCurrentItem(target_item)
            self.tree.scrollToItem(target_item)
        else:
            # 默认选第一个可选的叶子节点
            leaf = self._first_leaf()
            if leaf is not None:
                self.tree.setCurrentItem(leaf)

    def _first_leaf(self) -> QTreeWidgetItem | None:
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            if parent.childCount():
                return parent.child(0)
        return None

    def _on_tree_selection(self) -> None:
        if self._loading_group:
            return
        item = self.tree.currentItem()
        if item is None or item.childCount():
            return
        game = item.data(0, Qt.UserRole)
        if not game:
            return
        self._populate_files(str(game))

    def _populate_files(self, game: str) -> None:
        self._loading_group = True
        self.list_widget.clear()
        files = [
            v for v in self.all_versions
            if game in [short_game_version(g) for g in v.get("game_versions") or []]
        ]
        # 推荐版本（release 且最新）排第一
        files.sort(
            key=lambda v: (
                0 if str(v.get("release_type")) == "release" else 1,
                -self._timestamp(v.get("date_published")),
            )
        )
        self.versions = files
        for index, version in enumerate(files):
            item = self._build_row(version, index, index == 0)
            self.list_widget.addItem(item)
            widget = getattr(item, "_row_widget", None)
            if widget is not None:
                self.list_widget.setItemWidget(item, widget)

        self.file_title.setText(f"可用文件 · {game}")
        if files:
            self.list_widget.setCurrentRow(0)
            self.status_label.setText(
                f"{game} 共 {len(files)} 个文件，第一行为推荐版本。"
            )
        else:
            self.selected_version = None
            self.yesButton.setEnabled(False)
            self.status_label.setText(f"{game} 没有可用文件。")
        self._loading_group = False

    @staticmethod
    def _timestamp(value: Any) -> float:
        import datetime

        text = str(value or "").strip()
        if not text:
            return 0.0
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.datetime.fromisoformat(text).timestamp()
        except (ValueError, OSError, OverflowError):
            return 0.0

    def _build_row(self, version: dict[str, Any], index: int, recommended: bool) -> QListWidgetItem:
        name = str(version.get("name") or version.get("version_number") or "未命名")
        item = QListWidgetItem()

        row = QWidget(self.list_widget)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title = StrongBodyLabel(f"★ 推荐 · {name}" if recommended else name, row)
        if recommended:
            font = title.font()
            font.setWeight(QFont.DemiBold)
            title.setFont(font)
            title.setTextColor(QColor("#0F6CBD"), QColor("#4CC2FF"))
        layout.addWidget(title)

        meta_parts = [RELEASE_LABELS.get(str(version.get("release_type")), "正式版")]
        date = str(version.get("date_published") or "")[:10]
        if date:
            meta_parts.append(date)
        size = int((version.get("file") or {}).get("size") or 0)
        if size:
            meta_parts.append(f"{size / 1048576:.1f} MB")
        meta = CaptionLabel(" · ".join(meta_parts), row)
        meta.setTextColor(palette()["secondary"], palette()["secondary"])
        layout.addWidget(meta)

        item.setSizeHint(row.sizeHint())
        item.setData(Qt.UserRole, index)
        item._row_widget = row  # type: ignore[attr-defined]
        return item

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.versions):
            self.selected_version = None
            self.yesButton.setEnabled(False)
            return
        self.selected_version = self.versions[row]
        self.yesButton.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self._failed = True
        self.status_label.setText(f"读取失败：{message}")
        self.yesButton.setEnabled(False)

    def validate(self) -> bool:
        return self.selected_version is not None
