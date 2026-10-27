from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, PushButton, SimpleCardWidget, TitleLabel

from ...services import LauncherService
from ..theme import palette
from ..widgets import BlockLogo, EmptyState, HeroCard, SectionHeader, StatCard, VersionRow


class HomePage(QWidget):
    playRequested = Signal(str)
    browseRequested = Signal()
    manageRequested = Signal()

    def __init__(self, service: LauncherService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("homePage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#homePage {{ background: transparent; }}")
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("主页", self)
        title.setStyleSheet("font-size: 26px; font-weight: 600;")
        titles.addWidget(title)
        subtitle = QLabel("欢迎回来，准备开始新的冒险。", self)
        subtitle.setStyleSheet(f"color: {palette()['secondary']}; font-size: 10pt;")
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        outer.addLayout(header)

        hero = HeroCard(self)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(34, 22, 28, 22)
        hero_layout.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(8)
        eyebrow = QLabel("MINECRAFT JAVA EDITION", hero)
        eyebrow.setStyleSheet("color: rgba(255,255,255,0.62); font-size: 8pt; font-weight: 600; letter-spacing: 2px;")
        left.addWidget(eyebrow)

        headline = QLabel("开始下一段冒险", hero)
        headline.setStyleSheet("color: white; font-size: 25pt; font-weight: 600;")
        left.addWidget(headline)

        description = QLabel("原版生存、创造与冒险。启动器已经帮你处理好 Java、依赖和资源。", hero)
        description.setWordWrap(True)
        description.setStyleSheet("color: rgba(255,255,255,0.78); font-size: 10pt;")
        left.addWidget(description)
        left.addSpacing(6)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.version_combo = QComboBox(hero)
        self.version_combo.setFixedWidth(180)
        self.version_combo.setFixedHeight(40)
        self.version_combo.setStyleSheet(
            """
            QComboBox {
                background: rgba(255,255,255,0.16); color: white; border: 1px solid rgba(255,255,255,0.28);
                border-radius: 8px; padding: 0 12px; font-weight: 600;
            }
            QComboBox:hover { background: rgba(255,255,255,0.22); }
            QComboBox::drop-down { border: none; width: 26px; }
            QComboBox QAbstractItemView { background: #1E1E1E; color: white; border-radius: 8px; selection-background-color: #0F6CBD; }
            """
        )
        actions.addWidget(self.version_combo)

        self.play_button = QPushButton("启动游戏", hero)
        self.play_button.setFixedHeight(40)
        self.play_button.setMinimumWidth(132)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.setStyleSheet(
            """
            QPushButton {
                background: white; color: #0A3557; border: none; border-radius: 8px;
                padding: 0 22px; font-weight: 700; font-size: 10pt;
            }
            QPushButton:hover { background: #F0F6FF; }
            QPushButton:pressed { background: #E0EDF9; }
            QPushButton:disabled { background: rgba(255,255,255,0.35); color: rgba(10,53,87,0.6); }
            """
        )
        self.play_button.clicked.connect(self._request_play)
        actions.addWidget(self.play_button)

        self.browse_button = QPushButton("管理版本", hero)
        self.browse_button.setFixedHeight(40)
        self.browse_button.setCursor(Qt.PointingHandCursor)
        self.browse_button.setStyleSheet(
            """
            QPushButton {
                background: rgba(255,255,255,0.13); color: white; border: 1px solid rgba(255,255,255,0.25);
                border-radius: 8px; padding: 0 18px; font-weight: 600;
            }
            QPushButton:hover { background: rgba(255,255,255,0.22); }
            """
        )
        self.browse_button.clicked.connect(self.browseRequested.emit)
        actions.addWidget(self.browse_button)
        actions.addStretch(1)
        left.addLayout(actions)
        left.addStretch(1)
        hero_layout.addLayout(left, 1)

        logo = BlockLogo(hero)
        logo.setFixedSize(210, 210)
        hero_layout.addWidget(logo, 0, Qt.AlignRight | Qt.AlignVCenter)
        outer.addWidget(hero)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.installed_stat = StatCard(FluentIcon.LIBRARY, "已安装版本", "0", "本地版本", self)
        self.account_stat = StatCard(FluentIcon.PEOPLE, "当前账号", "Player", "离线账号", self)
        self.java_stat = StatCard(FluentIcon.CODE, "Java 运行时", "自动", "启动时自动选择", self)
        stats.addWidget(self.installed_stat)
        stats.addWidget(self.account_stat)
        stats.addWidget(self.java_stat)
        outer.addLayout(stats)

        section = SectionHeader("已安装版本", "这些版本已经可以离线启动", self)
        manage_button = PushButton(self)
        manage_button.setText("查看全部")
        manage_button.setIcon(FluentIcon.RIGHT_ARROW)
        manage_button.clicked.connect(self.manageRequested.emit)
        section.layout().addWidget(manage_button)
        outer.addWidget(section)

        self.versions_card = SimpleCardWidget(self)
        self.versions_card.setMinimumHeight(112)
        self.versions_layout = QVBoxLayout(self.versions_card)
        self.versions_layout.setContentsMargins(10, 8, 10, 8)
        self.versions_layout.setSpacing(2)
        outer.addWidget(self.versions_card)
        outer.addStretch(1)

    def _request_play(self) -> None:
        version_id = self.version_combo.currentData()
        if version_id:
            self.playRequested.emit(str(version_id))

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"QWidget#homePage {{ background: {palette()['bg']}; }}")

    def refresh(self) -> None:
        installed = self.service.installed_versions()
        account = self.service.account()
        selected = self.version_combo.currentData()

        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for item in installed:
            self.version_combo.addItem(item["id"], item["id"])
        if not installed:
            self.version_combo.addItem("还没有安装版本", None)
        elif selected:
            index = self.version_combo.findData(selected)
            if index >= 0:
                self.version_combo.setCurrentIndex(index)
        self.version_combo.blockSignals(False)
        self.play_button.setEnabled(bool(installed))

        self.installed_stat.set_value(str(len(installed)), "本地版本")
        if account:
            self.account_stat.set_value(account["name"], "微软正版" if not account["offline"] else "离线账号")
        else:
            self.account_stat.set_value("未登录", "请到账号页设置")
        self.java_stat.set_value("自动", "启动时自动选择")

        while self.versions_layout.count():
            item = self.versions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if installed:
            for item in installed[:4]:
                row = VersionRow(item, self.versions_card)
                row.playRequested.connect(self.playRequested.emit)
                self.versions_layout.addWidget(row)
        else:
            self.versions_layout.addWidget(
                EmptyState(
                    FluentIcon.DOWNLOAD,
                    "还没有安装任何版本",
                    "去「版本」页选择一个版本安装，装好后就能在这里直接启动。",
                    self.versions_card,
                )
            )
