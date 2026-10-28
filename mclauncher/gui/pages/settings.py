from __future__ import annotations

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PySide6.QtGui import QFont
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SettingCardGroup,
    SmoothScrollArea,
    SpinBox,
    SwitchButton,
    TitleLabel,
)

from ...services import LauncherService
from ..theme import ACCENTS, palette
from ..widgets import SettingRow
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
        # 👇 替换 setStyleSheet
        font = title.font()
        font.setPixelSize(26)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)

        outer.addWidget(title)

        # 👇 QLabel 换成 CaptionLabel
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

        appearance = SettingCardGroup("外观", container)
        self.theme_combo = ComboBox(container)
        self.theme_combo.addItem("跟随系统", userData="auto")
        self.theme_combo.addItem("浅色", userData="light")
        self.theme_combo.addItem("深色", userData="dark")
        self.theme_combo.setFixedWidth(160)
        appearance.addSettingCard(
            SettingRow(FluentIcon.BRIGHTNESS, "主题", "跟随系统会自动使用 Windows 的浅色/深色模式。", self.theme_combo)
        )

        self.accent_combo = ComboBox(container)
        for key, label in (("blue", "Fluent 蓝"), ("green", "森林绿"), ("purple", "典雅紫"), ("orange", "活力橙")):
            self.accent_combo.addItem(label, userData=key)
        self.accent_combo.setFixedWidth(160)
        appearance.addSettingCard(
            SettingRow(FluentIcon.PALETTE, "强调色", "按钮、选中态与进度条使用的品牌色。", self.accent_combo)
        )
        content.addWidget(appearance)

        performance = SettingCardGroup("性能与启动", container)
        # 删掉 SpinBox，换成 LineEdit
        self.memory_input = LineEdit(container)
        self.memory_input.setFixedWidth(160)
        self.memory_input.setPlaceholderText("例如 4096")
        # 只允许输入数字
        from PySide6.QtGui import QIntValidator
        self.memory_input.setValidator(QIntValidator(512, 32768, self))

        performance.addSettingCard(
            SettingRow(FluentIcon.SPEED_HIGH, "最大内存 (MB)", "分配给 Minecraft 的 JVM 堆上限，默认 4096。", self.memory_input)
        )


        self.java_combo = ComboBox(container)
        self.java_combo.addItem("自动选择（推荐）", userData="")
        self.java_combo.setMinimumWidth(300)
        performance.addSettingCard(
            SettingRow(FluentIcon.CODE, "Java 运行时", "优先使用 Mojang 下载的运行时；也可以指定本机 Java。", self.java_combo)
        )
        self.java_hint = CaptionLabel("正在检测 Java…", container)
        self.java_hint.setTextColor(palette()["tertiary"], palette()["tertiary"])
        performance.addSettingCard(
            SettingRow(FluentIcon.INFO, "检测结果", "启动时如果缺少 Java，会自动下载匹配的运行时。", self.java_hint)
        )
        content.addWidget(performance)

        self.isolate_switch = SwitchButton(container)
        self.isolate_switch.setOnText("启用")
        self.isolate_switch.setOffText("禁用")
        self.isolate_switch.setChecked(False)
        performance.addSettingCard(
            SettingRow(
                FluentIcon.FOLDER,
                "版本隔离",
                "为每个版本使用独立的 mods / saves / 配置，避免不同版本的模组与存档互相干扰。",
                self.isolate_switch,
            )
        )

        paths = SettingCardGroup("目录", container)
        self.game_dir_input = LineEdit(container)
        self.game_dir_input.setMinimumWidth(340)
        self.game_dir_input.setPlaceholderText("例如 D:\\Minecraft")
        browse = PushButton(container)
        browse.setText("浏览…")
        browse.setIcon(FluentIcon.FOLDER)
        browse.clicked.connect(self._browse_game_dir)
        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_row.addWidget(self.game_dir_input)
        game_row.addWidget(browse)
        game_widget = QWidget(container)
        game_widget.setLayout(game_row)
        paths.addSettingCard(
            SettingRow(FluentIcon.FOLDER, "游戏目录", "版本、依赖、资源与 Java 运行时的存放位置。", game_widget)
        )

        self.config_dir_label = CaptionLabel("", container)
        self.config_dir_label.setTextColor(palette()["secondary"], palette()["secondary"])
        paths.addSettingCard(
            SettingRow(FluentIcon.SETTING, "配置目录", "配置与登录 token 保存在这里（只读展示）。", self.config_dir_label)
        )

        self.offline_input = LineEdit(container)
        self.offline_input.setMaxLength(16)
        self.offline_input.setFixedWidth(220)
        paths.addSettingCard(
            SettingRow(FluentIcon.ROBOT, "离线用户名", "没有登录微软账号时使用的玩家名。", self.offline_input)
        )
        content.addWidget(paths)
        content.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_button = PrimaryPushButton(self)
        self.save_button.setText("保存设置")
        self.save_button.setIcon(FluentIcon.SAVE)
        self.save_button.setFixedHeight(38)
        self.save_button.setMinimumWidth(132)
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
            "game_dir": self.game_dir_input.text().strip(),
            "offline_name": self.offline_input.text().strip(),
            "isolate_versions": self.isolate_switch.isChecked(),  # ← 新增
        }
        self.saveRequested.emit(values)

    def refresh(self) -> None:
        settings = self.service.settings()
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.get("theme"))))
        self.accent_combo.setCurrentIndex(max(0, self.accent_combo.findData(settings.get("accent"))))
        self.memory_input.setText(str(settings.get("memory_mb") or 4096))
        self.game_dir_input.setText(str(settings.get("game_dir") or ""))
        self.config_dir_label.setText(str(settings.get("config_dir") or ""))
        self.isolate_switch.setChecked(bool(settings.get("isolate_versions")))
        self.offline_input.setText(str(settings.get("offline_name") or "Player"))

        configured = str(settings.get("java_path") or "")

        # 👇 关键修复：只有在第一次加载时，才重置下拉框
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
            # 如果已经加载过了，只同步当前选中状态，绝对不要清空
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

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"QWidget#settingsPage {{ background: {palette()['bg']}; }}")
        self._apply_input_styles()


def _on_isolate_toggled(self, checked: bool) -> None:
        try:
            self.service.save_settings({"isolate_versions": checked})
        except Exception as exc:
            InfoBar.error("保存失败", str(exc), parent=self)
            return
        # 提示用户：已安装的版本需要重新启动一次才会生效
        InfoBar.info(
            "版本隔离已切换",
            "下次启动游戏时生效；已有存档仍保留在原位置。",
            parent=self,
            duration=3000,
        )
