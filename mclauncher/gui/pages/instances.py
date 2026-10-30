from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QAbstractListModel, QModelIndex

from PySide6.QtGui import QFont, QDesktopServices, QIntValidator, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QLabel,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SettingCardGroup,
    SmoothScrollArea,
    SwitchButton,
    TabWidget,
    TitleLabel,
    TransparentToolButton,
    StrongBodyLabel,
    MessageBox,
    ListView,
)

from ...services import LauncherService
from ..theme import palette
from ..widgets import SettingRow, EmptyState
from ...util import human_size

class InstanceListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._instances: list[str] = []

    def set_instances(self, instances: list[str]):
        self.beginResetModel()
        self._instances = instances
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._instances)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._instances)):
            return None
        if role in (Qt.DisplayRole, Qt.UserRole):
            return self._instances[index.row()]
        return None

class InstancesPage(QWidget):
    def __init__(self, service: LauncherService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("instancesPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#instancesPage { background: transparent; }")

        self._current_version = ""
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(16)

        # 顶部标题区
        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)

        title = TitleLabel("实例管理", self)
        font = title.font()
        font.setPixelSize(26)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)
        titles.addWidget(title)

        subtitle = CaptionLabel("管理各版本的独立配置、Mod、资源包与世界存档。", self)
        subtitle.setTextColor(QColor("#5C5C5C"), QColor("#C8C8C8"))  # 跟随主题的灰色
        titles.addWidget(subtitle)

        header.addLayout(titles)
        header.addStretch(1)
        outer.addLayout(header)

        # 左右分栏
        content = QHBoxLayout()
        content.setSpacing(16)

        # 左侧：实例列表
        left_card = QWidget(self)
        left_card.setFixedWidth(220)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 替换为 ListView
        self.list_view = ListView(left_card)
        self.list_model = InstanceListModel(self)
        self.list_view.setModel(self.list_model)

        self.list_view.selectionModel().currentChanged.connect(self._on_selected)
        left_layout.addWidget(self.list_view)

        content.addWidget(left_card)

        # 右侧：Tab 容器
        self.right_card = QWidget(self)
        right_layout = QVBoxLayout(self.right_card)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self.empty_hint = CaptionLabel("请从左侧选择一个实例以查看和管理。", self.right_card)
        self.empty_hint.setTextColor(palette()["secondary"], palette()["secondary"])
        self.empty_hint.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.empty_hint)

        self.tab_widget = TabWidget(self.right_card)
        self.tab_widget.setVisible(False)

        # 构建各个 Tab 页面
        self.tab_settings = self._build_settings_tab()
        self.tab_mods = self._build_file_manager_tab("mods", "Mod 管理", "*.jar*")
        self.tab_resources = self._build_file_manager_tab("resourcepacks", "资源包管理", "*.zip")
        self.tab_saves = self._build_saves_tab()

        self.tab_widget.addTab(self.tab_settings, "独立设置", icon=FluentIcon.SETTING)
        self.tab_widget.addTab(self.tab_mods, "Mod 管理", icon=FluentIcon.ZIP_FOLDER)
        self.tab_widget.addTab(self.tab_resources, "资源包", icon=FluentIcon.PHOTO)
        self.tab_widget.addTab(self.tab_saves, "世界存档", icon=FluentIcon.FOLDER)

        right_layout.addWidget(self.tab_widget)
        content.addWidget(self.right_card, 1)
        outer.addLayout(content, 1)

        self._load_javas()

    # ------------------------------------------------------------------
    # Tab 1: 独立设置
    # ------------------------------------------------------------------
    def _build_settings_tab(self) -> QWidget:
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 20, 10)
        layout.setSpacing(16)

        self.base_group = SettingCardGroup("基础配置", container)
        self.memory_input = LineEdit(container)
        self.memory_input.setFixedWidth(160)
        self.memory_input.setPlaceholderText("例如 4096")
        self.memory_input.setValidator(QIntValidator(512, 32768, self))
        self.base_group.addSettingCard(
            SettingRow(FluentIcon.SPEED_HIGH, "最大内存 (MB)", "留空则使用全局配置。", self.memory_input))

        self.java_combo = ComboBox(container)
        self.java_combo.addItem("跟随全局设置", userData="")
        self.java_combo.setMinimumWidth(300)
        self.base_group.addSettingCard(
            SettingRow(FluentIcon.CODE, "Java 运行时", "为该实例单独指定 Java。", self.java_combo))

        self.isolate_switch = SwitchButton(container)
        self.isolate_switch.setOnText("独立")
        self.isolate_switch.setOffText("共享")
        self.base_group.addSettingCard(
            SettingRow(FluentIcon.FOLDER, "版本隔离", "开启后，该版本的 mods / saves 等将保存在该版本文件夹下。",
                       self.isolate_switch))

        layout.addWidget(self.base_group)

        btn_layout = QHBoxLayout()
        self.reset_btn = PushButton("恢复全局", container)
        self.reset_btn.setIcon(FluentIcon.SYNC)
        self.reset_btn.clicked.connect(self._reset_instance)
        btn_layout.addWidget(self.reset_btn)

        self.save_btn = PrimaryPushButton("保存设置", container)
        self.save_btn.setIcon(FluentIcon.SAVE)
        self.save_btn.clicked.connect(self._save_instance)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    # ------------------------------------------------------------------
    # Tab 2 & 3: Mod 与 资源包 (通用文件列表)
    # ------------------------------------------------------------------
    def _build_file_manager_tab(self, subdir_name: str, title: str, pattern: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 20, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel(title))
        header.addStretch(1)
        open_btn = PushButton("打开文件夹")
        open_btn.setIcon(FluentIcon.FOLDER)
        open_btn.clicked.connect(lambda: self._open_dir(subdir_name))
        header.addWidget(open_btn)
        layout.addLayout(header)

        list_widget = QListWidget()
        list_widget.setStyleSheet(
            f"QListWidget {{ background: {palette()['card']}; border: 1px solid {palette()['border']}; border-radius: 8px; padding: 4px; }}")
        layout.addWidget(list_widget)

        # 存储相关引用以便刷新
        if subdir_name == "mods":
            self.mods_list = list_widget
            self.mods_pattern = pattern
        elif subdir_name == "resourcepacks":
            self.rps_list = list_widget
            self.rps_pattern = pattern

        return widget

    # ------------------------------------------------------------------
    # Tab 4: 世界存档
    # ------------------------------------------------------------------
    def _build_saves_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 20, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("世界存档"))
        header.addStretch(1)
        open_btn = PushButton("打开文件夹")
        open_btn.setIcon(FluentIcon.FOLDER)
        open_btn.clicked.connect(lambda: self._open_dir("saves"))
        header.addWidget(open_btn)
        layout.addLayout(header)

        self.saves_list = QListWidget()
        self.saves_list.setStyleSheet(
            f"QListWidget {{ background: {palette()['card']}; border: 1px solid {palette()['border']}; border-radius: 8px; padding: 4px; }}")
        layout.addWidget(self.saves_list)

        return widget

    # ------------------------------------------------------------------
    # 核心逻辑
    # ------------------------------------------------------------------
    def _load_javas(self) -> None:
        try:
            for row in self.service.javas():
                self.java_combo.addItem(f"{row['version']} — {row['path']}", userData=row["path"])
        except Exception:
            pass

    def refresh(self) -> None:
        installed = self.service.installed_versions()
        names = [item["id"] for item in installed]
        self.list_model.set_instances(names)

        if names:
            self.list_view.setCurrentIndex(self.list_model.index(0, 0))
        else:
            self._show_empty()

    def _on_selected(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid():
            self._show_empty()
            return

        self._current_version = current.data(Qt.UserRole)
        instance_conf = self.service.get_instance_settings(self._current_version)

        self.empty_hint.setVisible(False)
        self.tab_widget.setVisible(True)

        # 1. 更新设置页
        self.memory_input.setText(str(instance_conf.get("memory_mb", "")))
        java_path = instance_conf.get("java_path", "")
        index = self.java_combo.findData(java_path)
        self.java_combo.setCurrentIndex(index if index >= 0 else 0)

        isolate = instance_conf.get("isolate_versions")
        if isolate is None:
            isolate = bool(self.service.settings().get("isolate_versions"))
        self.isolate_switch.setChecked(bool(isolate))

        # 2. 刷新文件列表
        self._refresh_file_lists()

    def _show_empty(self) -> None:
        self._current_version = ""
        self.empty_hint.setVisible(True)
        self.tab_widget.setVisible(False)

    def _get_instance_subdir(self, subdir_name: str) -> Path:
        """获取当前实例特定子目录的路径（处理隔离逻辑）"""
        instance_conf = self.service.get_instance_settings(self._current_version)
        isolate = instance_conf.get("isolate_versions")
        if isolate is None:
            isolate = bool(self.service.settings().get("isolate_versions"))

        if isolate:
            path = self.service.paths.version_dir(self._current_version) / subdir_name
        else:
            path = self.service.paths.game_dir / subdir_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _open_dir(self, subdir_name: str) -> None:
        if not self._current_version: return
        path = self._get_instance_subdir(subdir_name)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _refresh_file_lists(self) -> None:
        # -- 刷新 Mods --
        self.mods_list.clear()
        mods_dir = self._get_instance_subdir("mods")
        for f in sorted(mods_dir.iterdir()):
            if f.is_file() and ".jar" in f.name.lower():
                item = QListWidgetItem()
                if f.name.endswith(".disabled"):
                    item.setText(f.name.replace(".disabled", ""))
                    item.setForeground(Qt.gray)
                    item.setToolTip("已禁用")
                else:
                    item.setText(f.name)
                    item.setForeground(Qt.white if palette()["bg"] == "#202020" else Qt.black)

                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.setContentsMargins(0, 0, 10, 0)

                size_str = human_size(f.stat().st_size)
                layout.addWidget(CaptionLabel(size_str))

                toggle_btn = TransparentToolButton(FluentIcon.SYNC)
                toggle_btn.setToolTip("启用/禁用")
                toggle_btn.clicked.connect(lambda _, p=f: self._toggle_mod(p))
                layout.addWidget(toggle_btn)

                del_btn = TransparentToolButton(FluentIcon.DELETE)
                del_btn.setToolTip("删除")
                del_btn.clicked.connect(lambda _, p=f: self._delete_file(p, "Mod"))
                layout.addWidget(del_btn)

                item.setSizeHint(widget.sizeHint())
                self.mods_list.addItem(item)
                self.mods_list.setItemWidget(item, widget)

        # -- 刷新资源包 --
        self.rps_list.clear()
        rps_dir = self._get_instance_subdir("resourcepacks")
        for f in sorted(rps_dir.iterdir()):
            if f.is_file() and f.name.endswith(".zip"):
                item = QListWidgetItem(f.name)
                self.rps_list.addItem(item)

        # -- 刷新存档 --
        self.saves_list.clear()
        saves_dir = self._get_instance_subdir("saves")
        for f in sorted(saves_dir.iterdir()):
            if f.is_dir():
                name = f.name
                # 尝试读取 levelname.txt
                level_name_file = f / "levelname.txt"
                if level_name_file.is_file():
                    try:
                        name = level_name_file.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass

                item = QListWidgetItem(f"{name}  ({f.name})")
                item.setData(Qt.UserRole, str(f))
                self.saves_list.addItem(item)

    def _toggle_mod(self, path: Path) -> None:
        try:
            if path.name.endswith(".disabled"):
                new_path = path.with_name(path.name.replace(".disabled", ""))
            else:
                new_path = path.with_name(path.name + ".disabled")
            path.rename(new_path)
            self._refresh_file_lists()
        except Exception as e:
            InfoBar.error("操作失败", str(e), parent=self)

    def _delete_file(self, path: Path, type_name: str) -> None:
        box = MessageBox(f"确认删除 {type_name}", f"你确定要删除 {path.name} 吗？此操作不可恢复。", self)
        if box.exec():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                self._refresh_file_lists()
            except Exception as e:
                InfoBar.error("删除失败", str(e), parent=self)

    def _save_instance(self) -> None:
        if not self._current_version: return
        mem_text = self.memory_input.text().strip()
        values = {
            "memory_mb": int(mem_text) if mem_text.isdigit() else None,
            "java_path": self.java_combo.currentData() or "",
            "isolate_versions": self.isolate_switch.isChecked(),
        }
        # 清理空值
        values = {k: v for k, v in values.items() if v not in (None, "")}
        if not self.isolate_switch.isChecked():
            # 如果显式关闭隔离，也要存 False
            values["isolate_versions"] = False

        self.service.save_instance_settings(self._current_version, values)
        self._refresh_file_lists()  # 切换隔离后路径变了，刷新一下列表
        InfoBar.success("已保存", f"{self._current_version} 的独立设置已生效。", parent=self)

    def _reset_instance(self) -> None:
        if not self._current_version: return
        self.service.save_instance_settings(self._current_version, {})
        self._on_selected(self.list_widget.currentItem(), None)
        InfoBar.info("已恢复", f"{self._current_version} 已恢复为全局设置。", parent=self)