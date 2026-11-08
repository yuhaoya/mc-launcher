from __future__ import annotations

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from PySide6.QtGui import QFont, QIntValidator
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,  # 👈 新增导入
    SettingCard,
    SettingCardGroup,
    SmoothScrollArea,
    SwitchButton,
    TitleLabel,
)

from ...services import LauncherService
from ..theme import ACCENTS, palette
from ..workers import Worker


class SettingsPage(QWidget):
    saveRequested = Signal(dict)

    def __init__(self, service: LauncherService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("settingsPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#settingsPage {{ background: transparent; }}")
        self._javas_loaded = False
        self._java_worker: Worker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(10)

        title = TitleLabel("设置", self)
        font = title.font()
        font.setPixelSize(26)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)
        outer.addWidget(title)

        subtitle = CaptionLabel("外观、内存、Java 与游戏目录。修改后点击底部保存。", self)
        outer.addWidget(subtitle)

        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 8, 8, 8)
        content.setSpacing(16)

        # ================= 外观 =================
        appearance = SettingCardGroup("外观", container)

        # 主题
        self.theme_card = SettingCard(
            FluentIcon.BRIGHTNESS, "主题", "跟随系统会自动使用 Windows 的浅色/深色模式。", appearance
        )
        self.theme_combo = ComboBox(self.theme_card)
        self.theme_combo.addItem("跟随系统", userData="auto")
        self.theme_combo.addItem("浅色", userData="light")
        self.theme_combo.addItem("深色", userData="dark")
        self.theme_combo.setFixedWidth(160)
        self.theme_card.hBoxLayout.addWidget(self.theme_combo, 0, Qt.AlignRight)
        self.theme_card.hBoxLayout.addSpacing(14)
        appearance.addSettingCard(self.theme_card)

        # 强调色
        self.accent_card = SettingCard(
            FluentIcon.PALETTE, "强调色", "按钮、选中态与进度条使用的品牌色。", appearance
        )
        self.accent_combo = ComboBox(self.accent_card)
        self.accent_combo.addItem("Fluent 蓝", userData="blue")
        self.accent_combo.addItem("森林绿", userData="green")
        self.accent_combo.addItem("典雅紫", userData="purple")
        self.accent_combo.addItem("活力橙", userData="orange")
        self.accent_combo.setFixedWidth(160)
        self.accent_card.hBoxLayout.addWidget(self.accent_combo, 0, Qt.AlignRight)
        self.accent_card.hBoxLayout.addSpacing(14)
        appearance.addSettingCard(self.accent_card)

        content.addWidget(appearance)

        # ================= 性能与启动 =================
        performance = SettingCardGroup("性能与启动", container)

        # 内存
        self.memory_card = SettingCard(
            FluentIcon.SPEED_HIGH, "最大内存 (MB)", "分配给 Minecraft 的 JVM 堆上限，默认 4096。", performance
        )
        self.memory_input = LineEdit(self.memory_card)
        self.memory_input.setFixedWidth(160)
        self.memory_input.setPlaceholderText("例如 4096")
        self.memory_input.setValidator(QIntValidator(512, 32768, self))
        self.memory_card.hBoxLayout.addWidget(self.memory_input, 0, Qt.AlignRight)
        self.memory_card.hBoxLayout.addSpacing(14)
        performance.addSettingCard(self.memory_card)

        # Java 运行时
        self.java_card = SettingCard(
            FluentIcon.CODE, "Java 运行时", "优先使用 Mojang 下载的运行时；也可以指定本机 Java。", performance
        )
        self.java_combo = ComboBox(self.java_card)
        self.java_combo.addItem("自动选择（推荐）", userData="")
        self.java_combo.setMinimumWidth(300)
        self.java_card.hBoxLayout.addWidget(self.java_combo, 0, Qt.AlignRight)
        self.java_card.hBoxLayout.addSpacing(14)
        performance.addSettingCard(self.java_card)

        # Java 检测结果
        self.java_hint_card = SettingCard(
            FluentIcon.INFO, "检测结果", "启动时如果缺少 Java，会自动下载匹配的运行时。", performance
        )
        self.java_hint = CaptionLabel("正在检测 Java…", self.java_hint_card)
        self.java_hint.setTextColor(palette()["tertiary"], palette()["tertiary"])
        self.java_hint_card.hBoxLayout.addWidget(self.java_hint, 0, Qt.AlignRight)
        self.java_hint_card.hBoxLayout.addSpacing(14)
        performance.addSettingCard(self.java_hint_card)

        # 版本隔离
        self.isolate_card = SettingCard(
            FluentIcon.FOLDER, "版本隔离",
            "为每个版本使用独立的 mods / saves / 配置，避免不同版本的模组与存档互相干扰。",
            performance
        )
        self.isolate_switch = SwitchButton(self.isolate_card)
        self.isolate_switch.setOnText("启用")
        self.isolate_switch.setOffText("禁用")
        self.isolate_switch.checkedChanged.connect(self._on_isolate_toggled)
        self.isolate_card.hBoxLayout.addWidget(self.isolate_switch, 0, Qt.AlignRight)
        self.isolate_card.hBoxLayout.addSpacing(14)
        performance.addSettingCard(self.isolate_card)

        content.addWidget(performance)

        # ================= 目录 =================
        paths = SettingCardGroup("目录", container)

        # 👇 游戏目录：改回 LineEdit + Button 的组合
        self.game_dir_card = SettingCard(
            FluentIcon.FOLDER, "游戏目录", "版本、依赖、资源与 Java 运行时的存放位置。", paths
        )
        self.game_dir_input = LineEdit(self.game_dir_card)
        self.game_dir_input.setMinimumWidth(300)
        self.game_dir_input.setPlaceholderText("例如 D:\\Minecraft")

        self.browse_button = PushButton("浏览…", self.game_dir_card)
        self.browse_button.setIcon(FluentIcon.FOLDER)
        self.browse_button.clicked.connect(self._browse_game_dir)

        self.game_dir_card.hBoxLayout.addWidget(self.game_dir_input, 0, Qt.AlignRight)
        self.game_dir_card.hBoxLayout.addSpacing(8)
        self.game_dir_card.hBoxLayout.addWidget(self.browse_button, 0, Qt.AlignRight)
        self.game_dir_card.hBoxLayout.addSpacing(14)
        paths.addSettingCard(self.game_dir_card)

        self.config_dir_card = SettingCard(
            FluentIcon.SETTING, "配置目录", "配置与登录 token 保存在这里（只读展示）。", paths
        )
        self.config_dir_label = CaptionLabel("", self.config_dir_card)
        self.config_dir_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.config_dir_card.hBoxLayout.addWidget(self.config_dir_label, 0, Qt.AlignRight)
        self.config_dir_card.hBoxLayout.addSpacing(14)
        paths.addSettingCard(self.config_dir_card)

        self.offline_card = SettingCard(
            FluentIcon.ROBOT, "离线用户名", "没有登录微软账号时使用的玩家名。", paths
        )
        self.offline_input = LineEdit(self.offline_card)
        self.offline_input.setMaxLength(16)
        self.offline_input.setFixedWidth(220)
        self.offline_card.hBoxLayout.addWidget(self.offline_input, 0, Qt.AlignRight)
        self.offline_card.hBoxLayout.addSpacing(14)
        paths.addSettingCard(self.offline_card)

        content.addWidget(paths)
        content.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        # ================= 底部保存按钮 =================
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_button = PrimaryPushButton("保存设置", self)
        self.save_button.setIcon(FluentIcon.SAVE)
        self.save_button.setFixedHeight(36)
        self.save_button.setMinimumWidth(120)
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.save_button)
        outer.addLayout(footer)

    # ------------------------------------------------------------------
    def _browse_game_dir(self) -> None:
        current = self.game_dir_input.text().strip()
        chosen = QFileDialog.getExistingDirectory(self, "选择游戏目录", current)
        if chosen:
            self.game_dir_input.setText(chosen)

    def _save(self) -> None:
        mem_text = self.memory_input.text().strip()
        memory_mb = int(mem_text) if mem_text.isdigit() else 4096

        values = {
            "theme": self.theme_combo.currentData(),
            "accent": self.accent_combo.currentData(),
            "memory_mb": memory_mb,
            "java_path": self.java_combo.currentData() or "",
            "game_dir": self.game_dir_input.text().strip(),  # 👈 读取输入框
            "offline_name": self.offline_input.text().strip(),
            "isolate_versions": self.isolate_switch.isChecked(),
        }
        self.saveRequested.emit(values)

    def refresh(self) -> None:
        settings = self.service.settings()

        # 外观
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.get("theme"))))
        self.accent_combo.setCurrentIndex(max(0, self.accent_combo.findData(settings.get("accent"))))

        # 性能
        self.memory_input.setText(str(settings.get("memory_mb") or 4096))
        self.isolate_switch.setChecked(bool(settings.get("isolate_versions")))

        # 目录
        self.game_dir_input.setText(str(settings.get("game_dir") or ""))  # 👈 设置输入框
        self.config_dir_label.setText(str(settings.get("config_dir") or ""))
        self.offline_input.setText(str(settings.get("offline_name") or "Player"))

        configured = str(settings.get("java_path") or "")
        if not self._javas_loaded and self._java_worker is None:
            self.java_combo.blockSignals(True)
            self.java_combo.clear()
            self.java_combo.addItem("自动选择（推荐）", userData="")
            if configured:
                self.java_combo.addItem(f"已配置：{configured}", userData=configured)
            self.java_combo.setCurrentIndex(0)
            self.java_combo.blockSignals(False)
            self._load_javas()
        else:
            self.java_combo.blockSignals(True)
            index = self.java_combo.findData(configured)
            if index >= 0:
                self.java_combo.setCurrentIndex(index)
            self.java_combo.blockSignals(False)

    def _load_javas(self) -> None:
        worker = Worker(lambda w: self.service.javas())
        worker.signals.result.connect(self._on_javas)
        worker.signals.error.connect(self._on_java_error)
        worker.signals.finished.connect(self._on_java_finished)
        self._java_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_javas(self, rows: list[dict]) -> None:
        self._javas_loaded = True
        configured = str(self.service.settings().get("java_path") or "")
        current = self.java_combo.currentData() or configured
        self.java_combo.blockSignals(True)
        self.java_combo.clear()
        self.java_combo.addItem("自动选择（推荐）", userData="")
        for row in rows:
            self.java_combo.addItem(f"{row['version']} — {row['path']}", userData=row["path"])
        if configured and self.java_combo.findData(configured) < 0:
            self.java_combo.addItem(f"已配置：{configured}", userData=configured)
        index = self.java_combo.findData(current)
        self.java_combo.setCurrentIndex(index if index >= 0 else 0)
        self.java_combo.blockSignals(False)
        self.java_hint.setText(f"检测到 {len(rows)} 个 Java；启动时仍会按版本要求选择。")

    def _on_java_error(self, message: str) -> None:
        self.java_hint.setText("未能完成 Java 检测；启动时会自动下载所需运行时。")
        self._javas_loaded = True

    def _on_java_finished(self) -> None:
        self._java_worker = None

    def _on_isolate_toggled(self, checked: bool) -> None:
        try:
            self.service.save_settings({"isolate_versions": checked})
        except Exception as exc:
            InfoBar.error("保存失败", str(exc), parent=self)
            return
        InfoBar.info(
            "版本隔离已切换", "下次启动游戏时生效；已有存档仍保留在原位置。",
            parent=self, duration=3000
        )

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"QWidget#settingsPage {{ background: {palette()['bg']}; }}")