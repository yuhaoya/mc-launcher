from __future__ import annotations

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SegmentedWidget,
    SimpleCardWidget,
    StrongBodyLabel,
    TitleLabel,
    TransparentToolButton,
    ComboBox,
)

from ...services import LauncherService
from ..models import TYPE_LABELS, VersionDelegate, VersionFilterProxy, VersionTableModel
from ..theme import palette, rgba
from ..widgets import SectionHeader, SettingRow
from ..workers import Worker


class VersionsPage(QWidget):
    installRequested = Signal(str)
    installFabricRequested = Signal(str)
    launchRequested = Signal(str)
    openFolderRequested = Signal(str)

    def _table_style(self) -> str:
        p = palette()
        return f"""
            QTableView {{
                background: transparent;
                border: none;
                outline: 0;
                color: {p['text']};
                selection-background-color: transparent;
            }}
            QTableView::item {{
                padding: 0 8px;
                border-bottom: 1px solid {rgba(p['border'], 0.55)};
            }}
            QTableView::item:hover {{
                background: {p['hover']};
            }}
            QTableView::item:selected {{
                background: {p['selected']};
                color: {p['text']};
            }}
            QHeaderView::section {{
                background: transparent;
                color: {p['tertiary']};
                border: none;
                border-bottom: 1px solid {p['border']};
                padding: 8px 8px;
                font-size: 8pt;
                font-weight: 600;
            }}
            QTableCornerButton::section {{
                background: transparent;
                border: none;
            }}
        """

    def __init__(self, service: LauncherService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("versionsPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#versionsPage {{ background: transparent; }}")
        self._loaded = False
        self._loading = False
        self._rows: list[dict] = []
        self._worker: Worker | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(16)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("版本", self)
        title.setStyleSheet("font-size: 26px; font-weight: 600;")
        titles.addWidget(title)
        subtitle = QLabel("浏览 Mojang 版本清单，安装后即可启动。", self)
        subtitle.setStyleSheet(f"color: {palette()['secondary']}; font-size: 10pt;")
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.count_label = CaptionLabel("尚未加载", self)
        self.count_label.setTextColor(palette()["secondary"], palette()["secondary"])
        header.addWidget(self.count_label, 0, Qt.AlignBottom)
        outer.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText("搜索版本，例如 1.21.5")
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self.search)

        self.segmented = SegmentedWidget(self)
        for key, text in (("all", "全部"), ("release", "正式版"), ("snapshot", "快照"), ("installed", "已安装")):
            self.segmented.addItem(key, text)
        self.segmented.setCurrentItem("all")
        self.segmented.currentItemChanged.connect(lambda _: self._apply_filters())
        toolbar.addWidget(self.segmented)
        toolbar.addStretch(1)
        self.refresh_button = TransparentToolButton(self)
        self.refresh_button.setIcon(FluentIcon.SYNC)
        self.refresh_button.setToolTip("刷新版本清单")
        self.refresh_button.clicked.connect(lambda: self.ensure_loaded(force=True))
        toolbar.addWidget(self.refresh_button)
        outer.addLayout(toolbar)

        content = QHBoxLayout()
        content.setSpacing(16)

        table_card = SimpleCardWidget(self)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(6, 6, 6, 6)
        table_layout.setSpacing(0)
        self.model = VersionTableModel(self)
        self.proxy = VersionFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView(table_card)
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(VersionDelegate(self.table))
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setStyleSheet(self._table_style())
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMouseTracking(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 118), (2, 140), (3, 94)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.doubleClicked.connect(self._activate_index)
        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        table_layout.addWidget(self.table)
        content.addWidget(table_card, 7)

        self.detail = SimpleCardWidget(self)
        self.detail.setMinimumWidth(310)
        self.detail.setMaximumWidth(380)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(22, 20, 22, 20)
        detail_layout.setSpacing(10)
        self.detail_eyebrow = CaptionLabel("版本详情", self.detail)
        self.detail_eyebrow.setTextColor(palette()["secondary"], palette()["secondary"])
        detail_layout.addWidget(self.detail_eyebrow)
        self.detail_title = TitleLabel("选择一个版本", self.detail)
        self.detail_title.setStyleSheet("font-size: 22px; font-weight: 600;")
        detail_layout.addWidget(self.detail_title)
        self.detail_badge = QLabel("", self.detail)
        self.detail_badge.setFixedHeight(24)
        self.detail_badge.setAlignment(Qt.AlignCenter)
        self.detail_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        detail_layout.addWidget(self.detail_badge, 0, Qt.AlignLeft)
        self.detail_note = CaptionLabel("从左侧列表选择一个版本查看详情。", self.detail)
        self.detail_note.setTextColor(palette()["secondary"], palette()["secondary"])
        self.detail_note.setWordWrap(True)
        detail_layout.addWidget(self.detail_note)
        detail_layout.addSpacing(6)
        self.detail_grid = QGridLayout()
        self.detail_grid.setHorizontalSpacing(16)
        self.detail_grid.setVerticalSpacing(9)
        detail_layout.addLayout(self.detail_grid)
        detail_layout.addStretch(1)

        self.loader_combo = ComboBox(self.detail)
        self.loader_combo.addItem("原版 (Vanilla)", userData="vanilla")
        self.loader_combo.addItem("Fabric", userData="fabric")
        self.loader_combo.setFixedHeight(32)
        self.loader_combo.setCurrentIndex(0)
        detail_layout.addWidget(self.loader_combo)

        self.primary_button = PrimaryPushButton(self.detail)
        self.primary_button.setText("安装此版本")
        self.primary_button.setIcon(FluentIcon.DOWNLOAD)
        self.primary_button.setFixedHeight(38)
        self.primary_button.setEnabled(False)
        self.primary_button.clicked.connect(self._primary_action)
        detail_layout.addWidget(self.primary_button)
        self.folder_button = PushButton(self.detail)
        self.folder_button.setText("打开版本目录")
        self.folder_button.setIcon(FluentIcon.FOLDER)
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(self._open_folder)
        detail_layout.addWidget(self.folder_button)
        content.addWidget(self.detail, 3)

        outer.addLayout(content, 1)

    # ------------------------------------------------------------------
    def ensure_loaded(self, force: bool = False) -> None:
        if self._loading:
            return
        if self._loaded and not force:
            return
        self._loading = True
        self.refresh_button.setEnabled(False)
        self.count_label.setText("正在加载版本清单…")
        worker = Worker(lambda w: self.service.versions(force=force))
        worker.signals.result.connect(self._on_loaded)
        worker.signals.error.connect(self._on_load_error)
        worker.signals.finished.connect(self._on_load_finished)
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_loaded(self, data: dict) -> None:
        self._loaded = True
        self._rows = list(data.get("versions") or [])
        current = self.current_version_id()
        self.model.set_versions(self._rows)
        self._apply_filters()
        self.count_label.setText(f"共 {len(self._rows)} 个版本")
        if current:
            self.select_version(current)
        elif self._rows:
            latest_release = next((row["id"] for row in self._rows if row.get("type") == "release"), self._rows[0]["id"])
            self.select_version(latest_release)

    def _on_load_error(self, message: str) -> None:
        self.count_label.setText("版本清单加载失败")
        InfoBar.error("无法加载版本清单", message, parent=self, position=InfoBarPosition.TOP_RIGHT)

    def _on_load_finished(self) -> None:
        self._loading = False
        self.refresh_button.setEnabled(True)
        self._worker = None

    # ------------------------------------------------------------------
    def current_version_id(self) -> str:
        index = self.table.currentIndex()
        if not index.isValid():
            return ""
        row = index.data(Qt.UserRole) or {}
        return str(row.get("id", ""))

    def select_version(self, version_id: str) -> None:
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            data = index.data(Qt.UserRole) or {}
            if data.get("id") == version_id:
                self.table.selectRow(row)
                self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
                return

    def _apply_filters(self) -> None:
        route = self.segmented.currentRouteKey() or "all"
        self.proxy.set_filters(
            query=self.search.text(),
            type_filter="all" if route in ("all", "installed") else route,
            only_installed=route == "installed",
        )
        self.count_label.setText(f"显示 {self.proxy.rowCount()} / {len(self._rows)} 个版本")
        if not self.table.currentIndex().isValid() and self.proxy.rowCount():
            self.table.selectRow(0)

    def _selection_changed(self, current, previous) -> None:
        if current.isValid():
            data = current.data(Qt.UserRole) or {}
            self._show_detail(data)
        else:
            self._show_detail({})

    def _show_detail(self, data: dict) -> None:
        while self.detail_grid.count():
            item = self.detail_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not data:
            self.detail_title.setText("选择一个版本")
            self.detail_badge.hide()
            self.detail_note.setText("从左侧列表选择一个版本查看详情。")
            self.primary_button.setEnabled(False)
            self.folder_button.setEnabled(False)
            return
        version_id = data.get("id", "")
        kind = data.get("type", "release")
        label = TYPE_LABELS.get(kind, kind)
        self.detail_title.setText(version_id)
        self.detail_badge.setText(label)
        self.detail_badge.show()
        color = {
            "release": "#0F6CBD",
            "snapshot": "#CA5010",
            "old_beta": "#7A7574",
            "old_alpha": "#7A7574",
        }.get(kind, "#7A7574")
        self.detail_badge.setStyleSheet(
            f"background: {rgba(color, 0.13)}; color: {color}; border: 1px solid {rgba(color, 0.42)};"
            "border-radius: 6px; padding: 0 10px; font-size: 8pt; font-weight: 600;"
        )
        installed = bool(data.get("installed"))
        self.detail_note.setText(
            "已安装，可以直接启动。" if installed else "未安装。安装会自动补齐客户端、依赖、资源与 Java。"
        )
        rows = [
            ("类型", label),
            ("发布时间", str(data.get("release_time", ""))[:10]),
            ("状态", "已安装" if installed else "未安装"),
        ]
        for row, (key, value) in enumerate(rows):
            key_label = CaptionLabel(key, self.detail)
            key_label.setTextColor(palette()["secondary"], palette()["secondary"])
            value_label = StrongBodyLabel(value, self.detail)
            self.detail_grid.addWidget(key_label, row, 0)
            self.detail_grid.addWidget(value_label, row, 1)
        self.primary_button.setEnabled(True)
        if installed:
            self.primary_button.setText("启动游戏")
            self.primary_button.setIcon(FluentIcon.PLAY)
            self.loader_combo.hide()  # 👈 已安装版本不需要选加载器，隐藏
        else:
            self.primary_button.setText("安装此版本")
            self.primary_button.setIcon(FluentIcon.DOWNLOAD)
            self.loader_combo.show()  # 👈 未安装版本，显示加载器选择
        self.folder_button.setEnabled(installed)

    def _primary_action(self) -> None:
        version_id = self.current_version_id()
        if not version_id:
            return
        data = self._selected_data()
        if data.get("installed"):
            self.launchRequested.emit(version_id)
        else:
            # 👇 判断下拉框选的是什么
            loader = self.loader_combo.currentData()
            print(f"👉 前端点击安装：version={version_id}, 选择的 loader={loader}")
            if loader == "fabric":
                self.installFabricRequested.emit(version_id)
            else:
                self.installRequested.emit(version_id)


    def _selected_data(self) -> dict:
        index = self.table.currentIndex()
        return dict(index.data(Qt.UserRole) or {}) if index.isValid() else {}

    def _activate_index(self, index) -> None:
        data = index.data(Qt.UserRole) or {}
        version_id = data.get("id")
        if not version_id:
            return
        if data.get("installed"):
            self.launchRequested.emit(str(version_id))
        else:
            # 👇 双击未安装的版本时，直接走默认的安装逻辑（根据下拉框）
            loader = self.loader_combo.currentData()
            if loader == "fabric":
                self.installFabricRequested.emit(str(version_id))
            else:
                self.installRequested.emit(str(version_id))

    def _open_folder(self) -> None:
        version_id = self.current_version_id()
        if version_id:
            self.openFolderRequested.emit(version_id)

    # ------------------------------------------------------------------
    def refresh_installed(self) -> None:
        installed = {item["id"] for item in self.service.installed_versions()}
        changed = False
        for row in self._rows:
            value = row.get("id") in installed
            if row.get("installed") != value:
                row["installed"] = value
                changed = True
        if changed:
            current = self.current_version_id()
            self.model.set_versions(self._rows)
            self._apply_filters()
            if current:
                self.select_version(current)
