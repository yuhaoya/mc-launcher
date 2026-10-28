from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ...services import LauncherService
from ..theme import palette
from ..widgets import AccountRow, AvatarCircle, EmptyState, SectionHeader
from ..workers import Worker


class LoginDialog(MessageBoxBase):
    """设备码登录对话框；worker 跑在后台，信号回主线程。"""

    def __init__(self, service: LauncherService, parent=None, auto_start: bool = True):
        super().__init__(parent)
        self.service = service
        self.account: dict[str, Any] | None = None
        self.cancel_event = threading.Event()
        self.worker: Worker | None = None
        self._build_ui()
        if auto_start:
            self._start()

    def _build_ui(self) -> None:
        self.titleLabel = SubtitleLabel("登录微软账号", self)
        self.viewLayout.addWidget(self.titleLabel)
        hint = BodyLabel("浏览器会打开微软授权页，登录后输入下面的代码。", self)
        hint.setTextColor(palette()["secondary"], palette()["secondary"])
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        self.code_label = QLabel("正在获取设备码…", self)
        self.code_label.setAlignment(Qt.AlignCenter)
        self.code_label.setMinimumHeight(72)
        self.code_label.setStyleSheet(
            f"""
            background: {palette()["card_alt"]}; color: {palette()["text"]};
            border: 1px solid {palette()["border"]}; border-radius: 8px;
            font-family: Consolas, monospace; font-size: 22pt; font-weight: 700;
            letter-spacing: 3px;
            """
        )
        self.viewLayout.addWidget(self.code_label)

        self.url_label = CaptionLabel("https://microsoft.com/link", self)
        self.url_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.url_label.setAlignment(Qt.AlignCenter)
        self.viewLayout.addWidget(self.url_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.copy_button = PushButton(self)
        self.copy_button.setText("复制代码")
        self.copy_button.setIcon(FluentIcon.COPY)
        self.copy_button.clicked.connect(self._copy_code)
        buttons.addWidget(self.copy_button)
        self.open_button = PushButton(self)
        self.open_button.setText("打开授权页")
        self.open_button.setIcon(FluentIcon.LINK)
        self.open_button.clicked.connect(self._open_url)
        buttons.addWidget(self.open_button)
        self.viewLayout.addLayout(buttons)

        self.status_label = CaptionLabel("等待微软返回设备码…", self)
        self.status_label.setTextColor(palette()["secondary"], palette()["secondary"])
        self.status_label.setWordWrap(True)
        self.viewLayout.addWidget(self.status_label)

        self.yesButton.hide()
        self.cancelButton.setText("取消")
        self.cancelButton.clicked.connect(self._cancel)
        self.widget.setMinimumWidth(520)

    def _start(self) -> None:
        worker = Worker(
            lambda w: self.service.login(
                open_browser=True,
                on_code=w.signals.code.emit,
                on_status=w.signals.status.emit,
                cancel_event=self.cancel_event,
            )
        )
        worker.signals.code.connect(self._on_code)
        worker.signals.status.connect(self._on_status)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        self.worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_code(self, data: dict) -> None:
        code = str(data.get("user_code") or "")
        url = str(data.get("verification_uri") or "https://microsoft.com/link")
        self.code_label.setText(code or "获取失败")
        self.url_label.setText(url)
        self.status_label.setText("等待授权… 完成后此窗口会自动关闭")
        self._verification_url = url

    def _on_status(self, status: str) -> None:
        if status == "waiting":
            self.status_label.setText("等待授权… 完成后此窗口会自动关闭")
        elif status == "authorizing":
            self.status_label.setText("正在验证 Xbox / Minecraft 档案…")
        elif status == "authenticating":
            self.status_label.setText("正在验证 Xbox / Minecraft 档案…")
        elif status == "authorized":
            self.status_label.setText("授权成功，正在获取 Minecraft 档案…")
        elif status == "done":
            self.status_label.setText("登录成功，正在刷新账号…")

    def _on_result(self, account: dict) -> None:
        self.account = account
        self.accept()

    def _on_error(self, message: str) -> None:
        if self.cancel_event.is_set():
            self.reject()
            return
        self.status_label.setText(message)
        self.status_label.setTextColor(palette()["danger"], palette()["danger"])
        InfoBar.error("登录失败", message, parent=self, position=InfoBarPosition.TOP_RIGHT)

    def _copy_code(self) -> None:
        code = self.code_label.text().strip()
        if code and "…" not in code:
            QApplication.clipboard().setText(code)
            self.status_label.setText("代码已复制到剪贴板")

    def _open_url(self) -> None:
        QDesktopServices.openUrl(QUrl(getattr(self, "_verification_url", "https://microsoft.com/link")))

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.reject()

    def reject(self) -> None:
        self.cancel_event.set()
        super().reject()


class AccountPage(QWidget):
    loginRequested = Signal()
    logoutRequested = Signal()
    offlineRequested = Signal(str)

    def __init__(self, service: LauncherService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("accountPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#accountPage {{ background: transparent; }}")
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(16)
        title = TitleLabel("账号", self)
        # 👇 替换 setStyleSheet
        font = title.font()
        font.setPixelSize(26)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)

        outer.addWidget(title)

        # 👇 QLabel 换成 CaptionLabel
        subtitle = CaptionLabel("使用微软正版账号联机，或者用离线账号快速开始。", self)
        outer.addWidget(subtitle)

        profile = SimpleCardWidget(self)
        profile_layout = QHBoxLayout(profile)
        profile_layout.setContentsMargins(22, 18, 22, 18)
        profile_layout.setSpacing(16)
        self.avatar = AvatarCircle("P", profile)
        profile_layout.addWidget(self.avatar)
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        self.name_label = SubtitleLabel("Player", profile)
        text_box.addWidget(self.name_label)
        self.kind_label = CaptionLabel("离线账号", profile)
        self.kind_label.setTextColor(palette()["secondary"], palette()["secondary"])
        text_box.addWidget(self.kind_label)
        self.uuid_label = CaptionLabel("", profile)
        self.uuid_label.setTextColor(palette()["tertiary"], palette()["tertiary"])
        text_box.addWidget(self.uuid_label)
        profile_layout.addLayout(text_box)
        profile_layout.addStretch(1)
        self.login_button = PrimaryPushButton(profile)
        self.login_button.setText("登录微软账号")
        self.login_button.setIcon(FluentIcon.PEOPLE)
        self.login_button.clicked.connect(self.loginRequested.emit)
        profile_layout.addWidget(self.login_button)
        self.logout_button = PushButton(profile)
        self.logout_button.setText("退出登录")
        self.logout_button.setIcon(FluentIcon.POWER_BUTTON)
        self.logout_button.clicked.connect(self.logoutRequested.emit)
        profile_layout.addWidget(self.logout_button)
        outer.addWidget(profile)

        outer.addWidget(SectionHeader("离线账号", "不验证微软账号；适合单人游戏与本地测试。", self))
        offline_card = SimpleCardWidget(self)
        offline_layout = QHBoxLayout(offline_card)
        offline_layout.setContentsMargins(22, 16, 22, 16)
        offline_layout.setSpacing(10)
        icon = IconWidget(FluentIcon.ROBOT, offline_card)
        icon.setFixedSize(22, 22)
        offline_layout.addWidget(icon)
        self.offline_input = LineEdit(offline_card)
        self.offline_input.setPlaceholderText("离线用户名，最多 16 个字符")
        self.offline_input.setMaxLength(16)
        self.offline_input.setFixedWidth(300)
        offline_layout.addWidget(self.offline_input)
        self.offline_button = PrimaryPushButton(offline_card)
        self.offline_button.setText("使用此名字")
        self.offline_button.clicked.connect(self._apply_offline)
        offline_layout.addWidget(self.offline_button)
        offline_layout.addStretch(1)
        outer.addWidget(offline_card)

        outer.addWidget(SectionHeader("已保存账号", "可以保存多个离线账号并随时切换。", self))
        self.accounts_card = SimpleCardWidget(self)
        self.accounts_layout = QVBoxLayout(self.accounts_card)
        self.accounts_layout.setContentsMargins(12, 12, 12, 12)
        self.accounts_layout.setSpacing(6)
        outer.addWidget(self.accounts_card)
        outer.addStretch(1)

        outer.addWidget(SectionHeader("微软正版", "支持 Xbox Live / Minecraft 档案，登录后自动刷新 token。", self))
        msa_card = SimpleCardWidget(self)
        msa_layout = QHBoxLayout(msa_card)
        msa_layout.setContentsMargins(22, 16, 22, 16)
        msa_layout.setSpacing(12)
        msa_icon = IconWidget(FluentIcon.GLOBE, msa_card)
        msa_icon.setFixedSize(24, 24)
        msa_layout.addWidget(msa_icon)
        msa_text = QVBoxLayout()
        msa_text.setSpacing(2)
        msa_text.addWidget(StrongBodyLabel("设备码登录", msa_card))
        note = CaptionLabel("不需要输入密码；在浏览器中完成授权即可。", msa_card)
        note.setTextColor(palette()["secondary"], palette()["secondary"])
        msa_text.addWidget(note)
        msa_layout.addLayout(msa_text)
        msa_layout.addStretch(1)
        self.msa_action = PushButton(msa_card)
        self.msa_action.setText("开始登录")
        self.msa_action.setIcon(FluentIcon.LINK)
        self.msa_action.clicked.connect(self.loginRequested.emit)
        msa_layout.addWidget(self.msa_action)
        outer.addWidget(msa_card)
        outer.addStretch(1)

    def refresh(self) -> None:
        account = self.service.account()
        if account:
            self.avatar.set_name(account["name"])
            self.name_label.setText(account["name"])
            kind = "微软正版账号" if not account["offline"] else "离线账号"
            self.kind_label.setText(kind)
            self.uuid_label.setText(f"UUID: {account['uuid']}")
            self.login_button.setVisible(bool(account["offline"]))
            self.logout_button.setVisible(not account["offline"])
            self.msa_action.setText("已登录" if not account["offline"] else "开始登录")
        else:
            self.avatar.set_name("?")
            self.name_label.setText("未设置账号")
            self.kind_label.setText("请选择一个账号类型")
            self.uuid_label.setText("")
            self.login_button.setVisible(True)
            self.logout_button.setVisible(False)
            self.msa_action.setText("开始登录")
        self.offline_input.setText(str(self.service.settings().get("offline_name") or "Player"))
        self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        while self.accounts_layout.count():
            item = self.accounts_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        accounts = self.service.list_accounts()
        if not accounts:
            self.accounts_layout.addWidget(
                EmptyState(FluentIcon.PEOPLE, "还没有保存的账号", "添加一个离线账号或登录微软正版。", self.accounts_card)
            )
            return
        for entry in accounts:
            row = AccountRow(entry, self.accounts_card)
            row.switchRequested.connect(self._switch_account)
            row.removeRequested.connect(self._remove_account)
            self.accounts_layout.addWidget(row)

    def _switch_account(self, name: str) -> None:
        try:
            self.service.switch_account(name)
        except Exception as exc:
            InfoBar.error("切换失败", str(exc), parent=self)
            return
        self.refresh()
        InfoBar.success("已切换账号", f"当前账号：{name}", parent=self, duration=2000)

    def _remove_account(self, name: str) -> None:
        try:
            self.service.remove_offline_account(name)
        except Exception as exc:
            InfoBar.error("删除失败", str(exc), parent=self)
            return
        self.refresh()
        InfoBar.info("已删除", f"已移除账号 {name}。", parent=self)

    def _apply_offline(self) -> None:
        name = self.offline_input.text().strip()
        if not name:
            InfoBar.warning("名字不能为空", "请输入 1–16 个字符的离线用户名。", parent=self)
            return
        self.offlineRequested.emit(name)
