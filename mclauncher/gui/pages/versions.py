from __future__ import annotations

import json

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    ListWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SegmentedWidget,
    SimpleCardWidget,
    StrongBodyLabel,
    TabWidget,
    TableView,
    TitleLabel,
    TransparentToolButton,
)

from ...services import LauncherService
from ..dialogs import VersionPickerDialog, short_game_version
from ..icons import ProjectIcon
from ..models import TYPE_LABELS, VersionDelegate, VersionFilterProxy, VersionTableModel
from ..theme import palette, rgba
from ..widgets import SectionHeader, SettingRow
from ..workers import Worker

SOURCE_LABELS = {"modrinth": "Modrinth", "curseforge": "CurseForge"}


class VersionsPage(QWidget):
    installRequested = Signal(str)
    installFabricRequested = Signal(str)
    installForgeRequested = Signal(str)
    launchRequested = Signal(str)
    openFolderRequested = Signal(str)
    uninstallRequested = Signal(str)
    contentRequested = Signal(dict)

    

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
        self._content_worker: Worker | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(16)

        # 顶部标题区
        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)

        title = TitleLabel("下载", self)
        font = title.font()
        font.setPixelSize(26)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)
        titles.addWidget(title)

        subtitle = CaptionLabel("下载游戏版本，或者搜索安装 Mod。", self)
        subtitle.setTextColor(QColor("#5C5C5C"), QColor("#C8C8C8"))  # 跟随主题的灰色
        titles.addWidget(subtitle)

        header.addLayout(titles)
        header.addStretch(1)
        outer.addLayout(header)

        # 引入 TabWidget
        self.tab_widget = TabWidget(self)
        self.version_tab = QWidget()
        self.content_tab = QWidget()

        # ============ Tab 1: 原有的版本列表 ============
        version_layout = QVBoxLayout(self.version_tab)
        version_layout.setContentsMargins(0, 10, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = SearchLineEdit(self.version_tab)
        self.search.setPlaceholderText("搜索版本，例如 1.21.5")
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self.search)

        self.segmented = SegmentedWidget(self.version_tab)
        for key, text in (("all", "全部"), ("release", "正式版"), ("snapshot", "快照"), ("installed", "已安装")):
            self.segmented.addItem(key, text)
        self.segmented.setCurrentItem("all")
        self.segmented.currentItemChanged.connect(lambda _: self._apply_filters())
        toolbar.addWidget(self.segmented)

        toolbar.addStretch(1)

        # 👇 补上遗漏的 count_label
        self.count_label = CaptionLabel("尚未加载", self.version_tab)
        self.count_label.setTextColor(palette()["secondary"], palette()["secondary"])
        toolbar.addWidget(self.count_label)

        self.refresh_button = TransparentToolButton(self.version_tab)
        self.refresh_button.setIcon(FluentIcon.SYNC)
        self.refresh_button.setToolTip("刷新版本清单")
        self.refresh_button.clicked.connect(lambda: self.ensure_loaded(force=True))
        toolbar.addWidget(self.refresh_button)
        version_layout.addLayout(toolbar)

        content = QHBoxLayout()
        content.setSpacing(16)

        # 表格卡片
        table_card = SimpleCardWidget(self.version_tab)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(0)
        self.model = VersionTableModel(self)
        self.proxy = VersionFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = TableView(table_card)
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(VersionDelegate(self.table))

        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMouseTracking(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)  # 可以在这里统一设置行高
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 100), (2, 120), (3, 90)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)

        self.table.doubleClicked.connect(self._activate_index)
        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        table_layout.setContentsMargins(10, 4, 10, 10)
        table_layout.addWidget(self.table)
        content.addWidget(table_card, 7)

        # 👇 补全遗漏的右侧详情面板
        self.detail = SimpleCardWidget(self.version_tab)
        self.detail.setMinimumWidth(310)
        self.detail.setMaximumWidth(380)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(22, 20, 22, 20)
        detail_layout.setSpacing(10)

        self.detail_eyebrow = CaptionLabel("版本详情", self.detail)
        self.detail_eyebrow.setTextColor(palette()["secondary"], palette()["secondary"])
        detail_layout.addWidget(self.detail_eyebrow)

        self.detail_title = TitleLabel("选择一个版本", self.detail)
        font = self.detail_title.font()
        font.setPixelSize(22)
        font.setWeight(QFont.DemiBold)
        self.detail_title.setFont(font)
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
        self.loader_combo.addItem("Forge", userData="forge")
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

        self.uninstall_button = PushButton(self.detail)
        self.uninstall_button.setText("卸载此版本")
        self.uninstall_button.setIcon(FluentIcon.DELETE)
        self.uninstall_button.setEnabled(False)
        self.uninstall_button.clicked.connect(self._uninstall)
        detail_layout.addWidget(self.uninstall_button)

        content.addWidget(self.detail, 3)
        version_layout.addLayout(content, 1)

        # ============ Tab 2: 模组 / 资源包下载 ============
        content_layout = QVBoxLayout(self.content_tab)
        content_layout.setContentsMargins(0, 10, 0, 0)
        content_layout.setSpacing(12)

        content_toolbar = QHBoxLayout()
        content_toolbar.setSpacing(10)

        self.content_kind = SegmentedWidget(self.content_tab)
        self.content_kind.addItem("mod", "模组")
        self.content_kind.addItem("resourcepack", "资源包")
        self.content_kind.setCurrentItem("mod")
        self.content_kind.currentItemChanged.connect(lambda _: self._content_kind_changed())
        content_toolbar.addWidget(self.content_kind)

        self.content_search_input = SearchLineEdit(self.content_tab)
        self.content_search_input.setPlaceholderText("搜索模组或资源包，例如 sodium")
        self.content_search_input.returnPressed.connect(self._search_content)
        content_toolbar.addWidget(self.content_search_input, 1)

        self.content_search_btn = PrimaryPushButton("搜索", self.content_tab)
        self.content_search_btn.setIcon(FluentIcon.SEARCH)
        self.content_search_btn.clicked.connect(self._search_content)
        content_toolbar.addWidget(self.content_search_btn)

        self.content_source_combo = ComboBox(self.content_tab)
        self.content_source_combo.addItem("Modrinth", userData="modrinth")
        self.content_source_combo.addItem("CurseForge", userData="curseforge")
        self.content_source_combo.setFixedWidth(140)
        self.content_source_combo.currentIndexChanged.connect(lambda _: self._content_source_changed())
        content_toolbar.addWidget(self.content_source_combo)
        content_layout.addLayout(content_toolbar)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        target_label = CaptionLabel("安装到", self.content_tab)
        target_label.setTextColor(palette()["secondary"], palette()["secondary"])
        filter_bar.addWidget(target_label)
        self.content_target_combo = ComboBox(self.content_tab)
        self.content_target_combo.setMinimumWidth(180)
        self.content_target_combo.setToolTip("模组会被放进这个实例的 mods 目录")
        self.content_target_combo.currentIndexChanged.connect(lambda _: self._on_target_changed())
        filter_bar.addWidget(self.content_target_combo)

        self.loader_label = CaptionLabel("加载器", self.content_tab)
        self.loader_label.setTextColor(palette()["secondary"], palette()["secondary"])
        filter_bar.addWidget(self.loader_label)
        self.content_loader_combo = ComboBox(self.content_tab)
        self.content_loader_combo.addItem("Fabric", userData="fabric")
        self.content_loader_combo.addItem("Forge", userData="forge")
        self.content_loader_combo.addItem("Quilt", userData="quilt")
        self.content_loader_combo.addItem("NeoForge", userData="neoforge")
        filter_bar.addWidget(self.content_loader_combo)

        filter_bar.addStretch(1)
        self.content_status = CaptionLabel("输入关键词开始搜索", self.content_tab)
        self.content_status.setTextColor(palette()["secondary"], palette()["secondary"])
        filter_bar.addWidget(self.content_status)
        content_layout.addLayout(filter_bar)

        self.content_list = ListWidget(self.content_tab)
        self.content_list.setSpacing(6)
        content_layout.addWidget(self.content_list, 1)

        # 组装 Tab
        self.tab_widget.addTab(self.version_tab, "游戏版本", icon=FluentIcon.LIBRARY)
        self.tab_widget.addTab(self.content_tab, "模组 / 资源包", icon=FluentIcon.ZIP_FOLDER)
        outer.addWidget(self.tab_widget, 1)

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
        self.populate_game_versions(self._rows)
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
            if data.get("id"):
                self.set_content_game_version(str(data["id"]))
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
        self.uninstall_button.setEnabled(installed)

    def _uninstall(self) -> None:
        version_id = self.current_version_id()
        if not version_id:
            return
        box = MessageBox(
            "卸载版本",
            f"确定要删除 {version_id} 吗？\\n版本文件（含隔离目录里的存档与 Mod）会被一起删除，无法恢复。",
            self.window(),
        )
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self.uninstallRequested.emit(version_id)

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
            if loader == "fabric":
                self.installFabricRequested.emit(version_id)
            elif loader == "forge":
                self.installForgeRequested.emit(version_id)
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
            elif loader == "forge":
                self.installForgeRequested.emit(version_id)
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

    # ------------------------------------------------------------------
    # 模组 / 资源包
    # ------------------------------------------------------------------
    def current_content_kind(self) -> str:
        return self.content_kind.currentRouteKey() or "mod"

    def _content_kind_changed(self) -> None:
        is_mod = self.current_content_kind() == "mod"
        # 资源包与加载器无关，只按游戏版本过滤
        for widget in (self.loader_label, self.content_loader_combo):
            widget.setVisible(is_mod)
        self.content_search_input.setPlaceholderText(
            "搜索模组，例如 sodium" if is_mod else "搜索资源包，例如 faithful"
        )
        self.content_list.clear()
        self.content_status.setText("输入关键词开始搜索")

    def set_content_game_version(self, version_id: str) -> None:
        """把版本页选中的版本同步到「安装到」下拉框。"""
        if not version_id:
            return
        index = self.content_target_combo.findData(version_id)
        if index >= 0:
            self.content_target_combo.setCurrentIndex(index)

    def populate_game_versions(self, versions: list[dict]) -> None:
        """记住完整版本清单，刷新「安装到」下拉框。"""
        self._all_versions = list(versions)
        self._rebuild_target_options()

    def _rebuild_target_options(self) -> None:
        """「安装到」只列已安装版本，决定模组落到哪个 mods 目录。"""
        current = self.content_target_combo.currentData()
        installed = [row for row in getattr(self, "_all_versions", []) if row.get("installed")]

        self.content_target_combo.blockSignals(True)
        self.content_target_combo.clear()
        if not installed:
            self.content_target_combo.addItem("（尚未安装任何版本）", userData="")
        else:
            for row in installed:
                version_id = str(row.get("id") or "")
                if version_id:
                    self.content_target_combo.addItem(version_id, userData=version_id)

        if current:
            index = self.content_target_combo.findData(current)
            if index >= 0:
                self.content_target_combo.setCurrentIndex(index)
        self.content_target_combo.blockSignals(False)

    def _on_target_changed(self) -> None:
        """切换安装目标后，加载器自动跟随该实例的类型。"""
        version_id = self._resolved_target_version()
        if not version_id:
            return
        lower = version_id.lower()
        for key in ("fabric", "forge", "quilt", "neoforge"):
            if key in lower:
                index = self.content_loader_combo.findData(key)
                if index >= 0:
                    self.content_loader_combo.setCurrentIndex(index)
                return

    def refresh_content_versions(self) -> None:
        """安装/卸载版本后刷新资源页的版本下拉框。"""
        try:
            data = self.service.versions()
        except Exception:
            return
        self.populate_game_versions(list(data.get("versions") or []))

    def _content_source_changed(self) -> None:
        source = self.content_source_combo.currentData()
        if source == "curseforge" and not self.service.curseforge_key():
            InfoBar.warning(
                "需要 API Key",
                "CurseForge 需要在「设置 → 内容源」里填写 API Key 才能搜索。",
                parent=self,
                duration=5000,
            )

    def _resolved_game_version(self) -> str:
        """搜索时用于过滤的游戏版本，取安装目标实例的版本号。"""
        return short_game_version(self._resolved_target_version())

    def _resolved_target_version(self) -> str:
        """模组实际安装到的实例（必须是已安装版本）。"""
        selected = self.content_target_combo.currentData()
        return str(selected) if selected else ""

    def _search_content(self) -> None:
        query = self.content_search_input.text().strip()
        if not query:
            InfoBar.warning("提示", "请输入搜索关键词", parent=self)
            return

        kind = self.current_content_kind()
        game_version = self._resolved_game_version() or None
        loader = None
        if kind == "mod":
            loader = self.content_loader_combo.currentData() or None
        source = self.content_source_combo.currentData() or "modrinth"

        self.content_list.clear()
        self.content_status.setText(f"正在搜索 {SOURCE_LABELS.get(source, source)} …")

        worker = Worker(
            lambda w: self.service.search_content(
                query,
                project_type=kind,
                game_version=game_version,
                loader=loader,
                limit=20,
                source=source,
            )
        )

        def on_success(data: dict) -> None:
            hits = data.get("hits") or []
            if not hits:
                self.content_status.setText("没有找到相关结果，换个关键词试试。")
                return
            self.content_status.setText(f"找到 {data.get('total', len(hits))} 个结果（显示前 {len(hits)} 个）")
            for hit in hits:
                hit["source"] = source
                self._append_content_row(hit, kind, game_version, loader)

        def on_error(message: str) -> None:
            self.content_status.setText("搜索失败")
            InfoBar.error("搜索出错", message, parent=self, position=InfoBarPosition.TOP_RIGHT)

        worker.signals.result.connect(on_success)
        worker.signals.error.connect(on_error)
        # 必须持有引用：局部变量在函数返回后会被回收，信号随之断开，
        # 回调永远不触发，界面会一直停在「正在搜索…」。
        self._content_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _append_content_row(self, hit: dict, kind: str, game_version: str | None, loader: str | None) -> None:
        item = QListWidgetItem()
        widget = self._build_content_item(hit, kind, game_version, loader)
        item.setSizeHint(widget.sizeHint())
        self.content_list.addItem(item)
        self.content_list.setItemWidget(item, widget)

    def _build_content_item(self, hit: dict, kind: str, game_version: str | None, loader: str | None) -> QWidget:
        row = QWidget(self.content_list)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(12)

        icon = ProjectIcon(44, row)
        icon.set_project(hit.get("title") or "", str(hit.get("icon_url") or ""))
        layout.addWidget(icon, 0, Qt.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = StrongBodyLabel(hit.get("title") or hit.get("slug") or "未知", row)
        texts.addWidget(title)
        desc = CaptionLabel(hit.get("description") or "", row)
        desc.setWordWrap(True)
        desc.setTextColor(palette()["secondary"], palette()["secondary"])
        texts.addWidget(desc)
        source_label = SOURCE_LABELS.get(str(hit.get("source") or ""), "")
        meta = CaptionLabel(
            f"作者 {hit.get('author') or '未知'} · 下载 {int(hit.get('downloads') or 0):,}"
            + (f" · {source_label}" if source_label else ""),
            row,
        )
        meta.setTextColor(palette()["tertiary"], palette()["tertiary"])
        texts.addWidget(meta)
        layout.addLayout(texts, 1)

        install_button = PrimaryPushButton("安装", row)
        install_button.setIcon(FluentIcon.DOWNLOAD)
        install_button.setFixedWidth(96)
        install_button.clicked.connect(
            lambda: self._choose_and_install(hit, kind, game_version, loader, install_button)
        )
        layout.addWidget(install_button, 0, Qt.AlignVCenter)

        return row

    def _choose_and_install(
        self,
        hit: dict,
        kind: str,
        game_version: str | None,
        loader: str | None,
        button,
    ) -> None:
        """弹出文件选择弹窗，选好后把下载任务交给任务管理页。"""
        target = self._resolved_target_version()
        if not target:
            InfoBar.warning(
                "先安装游戏版本",
                "「安装到」里还没有已安装的版本，请先在「游戏版本」页装好游戏。",
                parent=self,
                duration=5000,
            )
            return

        # 没有单独指定过滤版本时，按目标实例的游戏版本查文件
        lookup_version = game_version or short_game_version(target)
        dialog = VersionPickerDialog(hit, lookup_version, loader, self.service, self.window())
        if not dialog.exec():
            return
        chosen = dialog.selected_version
        if not chosen:
            return

        button.setEnabled(False)
        button.setText("已加入任务")
        self.contentRequested.emit(
            {
                "project": hit,
                "kind": kind,
                "game_version": lookup_version,
                "loader": loader,
                "chosen": chosen,
                "version_id": target,
            }
        )