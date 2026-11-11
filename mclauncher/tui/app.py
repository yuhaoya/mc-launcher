from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from ..services import LauncherService

RELEASE_LABELS = {"release": "正式版", "beta": "测试版", "alpha": "内测版"}

CSS = """
Screen {
    background: #0d1117;
    color: #c9d1d9;
}
Header {
    background: #161b22;
    color: #c9d1d9;
}
Footer {
    background: #161b22;
    color: #8b949e;
}
TabbedContent {
    height: 1fr;
}
TabPane {
    padding: 1 2;
    height: 1fr;
}
#hero {
    border: round #1f6feb;
    background: #161b22;
    padding: 1 2;
    margin-bottom: 1;
}
.card {
    border: round #30363d;
    background: #161b22;
    padding: 1 2;
    margin: 1 0;
}
.section {
    color: #58a6ff;
    text-style: bold;
    margin: 1 0 0 0;
}
.hint {
    color: #8b949e;
    margin-bottom: 1;
}
Input {
    margin: 0 0 1 0;
}
DataTable {
    height: 1fr;
    border: round #30363d;
    background: #0d1117;
}
#versions-status {
    height: 1;
    color: #8b949e;
}
#instances-table {
    height: 1fr;
}
#instance-detail {
    height: auto;
}
#confirm-body {
    padding: 1 2;
}
ConfirmScreen {
    align: center middle;
}
ConfirmScreen > Vertical {
    width: 60;
    height: auto;
    border: round #1f6feb;
    background: #161b22;
    padding: 1 2;
}
#download-progress {
    margin: 1 0;
}
#download-log {
    height: 1fr;
    border: round #30363d;
    background: #0d1117;
}
#account-log {
    height: 1fr;
    border: round #30363d;
    background: #0d1117;
}
Horizontal {
    height: auto;
}
Button {
    margin-right: 1;
}
VerticalScroll {
    height: 1fr;
}
"""


class ConfirmScreen(ModalScreen[bool]):
    """简单的确认弹窗，用于卸载等不可撤销操作。"""

    BINDINGS = [("escape", "dismiss(False)", "取消")]

    def __init__(self, title: str, body: str, confirm_text: str = "确认"):
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.confirm_text = confirm_text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold #58a6ff]{self.title_text}[/]", id="confirm-title")
            yield Static(self.body_text, id="confirm-body")
            with Horizontal():
                yield Button(self.confirm_text, id="confirm-yes", variant="error")
                yield Button("取消", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")


class MCLTuiApp(App):
    CSS = CSS
    TITLE = "Micalith Launcher TUI"
    SUB_TITLE = "Minecraft Java Edition 启动器"
    BINDINGS = [
        ("q", "quit", "退出"),
        ("r", "refresh", "刷新"),
        ("1", "tab('dashboard')", "仪表盘"),
        ("2", "tab('versions')", "版本"),
        ("3", "tab('content')", "模组"),
        ("4", "tab('downloads')", "下载"),
        ("5", "tab('instances')", "实例"),
        ("6", "tab('account')", "账号"),
        ("7", "tab('settings')", "设置"),
    ]

    def __init__(self, game_dir: str | Path | None = None, config_dir: str | Path | None = None):
        super().__init__()
        self.service = LauncherService(game_dir, config_dir)
        self._all_versions: list[dict[str, Any]] = []
        self._selected_version = ""
        self._dash_version = ""
        self._installed_ids: set[str] = set()
        self._installing = False
        self._install_cancel: threading.Event | None = None
        self._game_worker = None
        self._login_cancel: threading.Event | None = None
        self._versions_ready = False
        self._content_hits: list[dict[str, Any]] = []
        self._content_files: list[dict[str, Any]] = []
        self._content_installing = False

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("仪表盘", id="dashboard"):
                with VerticalScroll():
                    yield Static(
                        "[bold #58a6ff]Micalith Launcher[/]\n"
                        "[#8b949e]原版 Minecraft 启动器 · Fluent 2 UI / 终端双前端[/]\n\n"
                        "安装、启动与账号管理共用同一套启动核心。",
                        id="hero",
                    )
                    with Horizontal():
                        yield Static("", id="account-card", classes="card")
                        yield Static("", id="system-card", classes="card")
                    yield Static("已安装版本", classes="section")
                    yield Select([], id="dash-version", prompt="选择已安装版本")
                    with Horizontal():
                        yield Button("启动选中版本", id="dash-launch", variant="primary")
                        yield Button("刷新", id="dash-refresh")
                        yield Button("去安装", id="dash-browse")
                    yield DataTable(id="installed-table")
            with TabPane("版本", id="versions"):
                yield Input(placeholder="搜索版本，例如 1.21.5", id="version-search")
                with Horizontal():
                    yield Select(
                        [("全部", "all"), ("正式版", "release"), ("快照", "snapshot"), ("已安装", "installed")],
                        id="version-filter",
                        value="all",
                    )
                    yield Button("刷新清单", id="versions-refresh")
                    yield Button("安装 / 启动", id="versions-action", variant="primary")
                    yield Button("卸载", id="versions-uninstall", variant="error")
                yield DataTable(id="versions-table")
                yield Static("正在加载版本清单…", id="versions-status")
            with TabPane("模组", id="content"):
                yield Static("模组与资源包下载", classes="section")
                with Horizontal():
                    yield Select(
                        [("模组", "mod"), ("资源包", "resourcepack")],
                        id="content-kind",
                        value="mod",
                        allow_blank=False,
                    )
                    yield Select(
                        [("Modrinth", "modrinth"), ("CurseForge", "curseforge")],
                        id="content-source",
                        value="modrinth",
                        allow_blank=False,
                    )
                    yield Input(placeholder="搜索关键词，例如 sodium", id="content-search")
                    yield Button("搜索", id="content-search-btn", variant="primary")
                with Horizontal():
                    yield Label("已安装版本")
                    yield Select([], id="content-game", prompt="选择已安装版本")
                    yield Label("加载器")
                    yield Select(
                        [("Fabric", "fabric"), ("Forge", "forge"), ("Quilt", "quilt"), ("NeoForge", "neoforge")],
                        id="content-loader",
                        value="fabric",
                        allow_blank=False,
                    )
                yield Static("输入关键词后回车搜索。", id="content-status")
                yield DataTable(id="content-table")
                yield Static("可用文件（第一行为推荐版本）", classes="section")
                yield DataTable(id="content-files")
                with Horizontal():
                    yield Button("安装选中文件", id="content-install", variant="primary")
                    yield Button("打开内容目录", id="content-open")
            with TabPane("下载", id="downloads"):
                yield Static("下载与安装", classes="section")
                yield Static("当前没有安装任务。", id="download-status")
                yield ProgressBar(total=100, show_percentage=True, id="download-progress")
                with Horizontal():
                    yield Button("取消当前任务", id="download-cancel", disabled=True)
                    yield Button("清理日志", id="download-clear")
                yield RichLog(id="download-log", markup=True, wrap=True)
            with TabPane("实例", id="instances"):
                yield Static("版本隔离与实例目录", classes="section")
                yield Static(
                    "[#8b949e]开启隔离后，每个版本的 mods / saves / 配置都会存放在 versions/<版本>/ 下。[/]",
                    id="instances-hint",
                )
                yield DataTable(id="instances-table")
                with Horizontal():
                    yield Button("打开实例目录", id="instance-open")
                    yield Button("刷新", id="instance-refresh")
            with TabPane("账号", id="account"):
                yield Static("", id="account-detail", classes="card")
                with Horizontal():
                    yield Button("登录微软账号", id="login", variant="primary")
                    yield Button("退出登录", id="logout")
                yield Static("已保存账号", classes="section")
                yield DataTable(id="accounts-table")
                with Horizontal():
                    yield Button("切换到此账号", id="account-switch", variant="primary")
                    yield Button("删除账号", id="account-remove", variant="error")
                yield Static("新增离线账号", classes="section")
                yield Input(placeholder="离线用户名，1–16 个字符", id="offline-name")
                yield Button("添加并切换", id="offline-apply")
                yield RichLog(id="account-log", markup=True, wrap=True)
            with TabPane("设置", id="settings"):
                with VerticalScroll():
                    yield Static("启动与目录设置", classes="section")
                    yield Label("最大内存（MB）")
                    yield Input(id="memory-input", type="integer")
                    yield Label("游戏目录")
                    yield Input(id="game-dir-input")
                    yield Label("Java 路径（留空自动选择）")
                    yield Input(placeholder="例如 C:\\Java\\bin\\java.exe", id="java-input")
                    yield Static("版本隔离", classes="section")
                    with Horizontal():
                        yield Switch(id="isolate-switch")
                        yield Label("启用版本隔离（每个版本独立 mods / saves）", id="isolate-label")
                    yield Static("外观", classes="section")
                    yield Select(
                        [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")],
                        id="theme-select",
                        value="auto",
                    )
                    with Horizontal():
                        yield Button("保存设置", id="save-settings", variant="primary")
                        yield Button("恢复当前配置", id="reload-settings")
                    yield Static("", id="settings-status", classes="hint")
        yield Footer()

    # ------------------------------------------------------------------
    def on_mount(self) -> None:
        installed_table = self.query_one("#installed-table", DataTable)
        installed_table.cursor_type = "row"
        installed_table.add_columns("版本", "类型", "大小")
        versions_table = self.query_one("#versions-table", DataTable)
        versions_table.cursor_type = "row"
        versions_table.add_columns("版本", "类型", "发布时间", "状态")
        instances_table = self.query_one("#instances-table", DataTable)
        instances_table.cursor_type = "row"
        instances_table.add_columns("版本", "类型", "隔离目录", "存档数")
        accounts_table = self.query_one("#accounts-table", DataTable)
        accounts_table.cursor_type = "row"
        accounts_table.add_columns("玩家名", "类型", "UUID", "状态")
        content_table = self.query_one("#content-table", DataTable)
        content_table.cursor_type = "row"
        content_table.add_columns("名称", "作者", "下载量", "项目 ID")
        files_table = self.query_one("#content-files", DataTable)
        files_table.cursor_type = "row"
        files_table.add_columns("版本", "类型", "游戏版本", "发布时间")
        self.refresh_dashboard()
        self.load_settings()
        self.refresh_instances()
        self.load_versions()

    def refresh_dashboard(self) -> None:
        installed = self.service.installed_versions()
        self._installed_ids = {item["id"] for item in installed}
        account = self.service.account()
        if account:
            kind = "微软正版" if not account["offline"] else "离线账号"
            account_text = (
                f"[bold #58a6ff]当前账号[/]\n\n[bold]{account['name']}[/]\n"
                f"{kind}\n[#8b949e]UUID {account['uuid']}[/]"
            )
        else:
            account_text = "[bold #58a6ff]当前账号[/]\n\n[#8b949e]尚未设置账号[/]"
        self.query_one("#account-card", Static).update(account_text)
        self.query_one("#system-card", Static).update(
            f"[bold #58a6ff]运行环境[/]\n\n"
            f"Python 启动核心\n"
            f"[#8b949e]已安装 {len(installed)} 个版本[/]\n"
            f"[#8b949e]游戏目录 {self.service.paths.game_dir}[/]"
        )
        table = self.query_one("#installed-table", DataTable)
        table.clear()
        for item in installed:
            table.add_row(item["id"], item.get("type", "release"), item.get("size_text", ""), key=item["id"])
        select = self.query_one("#dash-version", Select)
        options = [(f"{item['id']}  ({item.get('size_text', '')})", item["id"]) for item in installed]
        select.set_options(options)
        if options:
            values = [value for _, value in options]
            keep = self._dash_version if self._dash_version in values else values[0]
            select.value = keep
            self._dash_version = keep
            select.disabled = False
            self.query_one("#dash-launch", Button).disabled = False
        else:
            select.disabled = True
            self.query_one("#dash-launch", Button).disabled = True

    def load_settings(self) -> None:
        settings = self.service.settings()
        self.query_one("#memory-input", Input).value = str(settings.get("memory_mb") or 4096)
        self.query_one("#game-dir-input", Input).value = str(settings.get("game_dir") or "")
        self.query_one("#java-input", Input).value = str(settings.get("java_path") or "")
        self.query_one("#offline-name", Input).value = str(settings.get("offline_name") or "Player")
        self.query_one("#theme-select", Select).value = str(settings.get("theme") or "auto")
        self.query_one("#isolate-switch", Switch).value = bool(settings.get("isolate_versions"))
        self.refresh_account()
        self.refresh_accounts()

    def refresh_instances(self) -> None:
        table = self.query_one("#instances-table", DataTable)
        table.clear()
        for item in self.service.installed_versions():
            instance_dir = self.service.paths.instance_dir(item["id"])
            saves = instance_dir / "saves"
            saves_count = 0
            if saves.is_dir():
                try:
                    saves_count = sum(1 for p in saves.iterdir() if p.is_dir())
                except OSError:
                    saves_count = 0
            exists = "已创建" if instance_dir.is_dir() else "未创建"
            table.add_row(
                item["id"],
                item.get("type", "release"),
                exists,
                str(saves_count),
                key=item["id"],
            )

    def refresh_accounts(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        table.clear()
        for entry in self.service.list_accounts():
            table.add_row(
                entry["name"],
                entry.get("kind", "离线账号"),
                str(entry.get("uuid", ""))[:8],
                "当前" if entry.get("active") else "",
                key=entry["name"],
            )

    def _selected_account_name(self) -> str:
        table = self.query_one("#accounts-table", DataTable)
        if table.cursor_row < 0:
            return ""
        row = table.get_row_at(table.cursor_row)
        return str(row[0]) if row else ""

    def _selected_instance_id(self) -> str:
        table = self.query_one("#instances-table", DataTable)
        if table.cursor_row < 0:
            return ""
        row = table.get_row_at(table.cursor_row)
        return str(row[0]) if row else ""

    def refresh_account(self) -> None:
        account = self.service.account()
        if not account:
            text = "[#8b949e]尚未设置账号。[/]"
        elif account["offline"]:
            text = (
                f"[bold #58a6ff]离线账号[/]\n\n[bold]{account['name']}[/]\n"
                f"[#8b949e]UUID {account['uuid']}[/]"
            )
        else:
            text = (
                f"[bold #58a6ff]微软正版账号[/]\n\n[bold]{account['name']}[/]\n"
                f"[#8b949e]UUID {account['uuid']}[/]"
            )
        self.query_one("#account-detail", Static).update(text)

    # ------------------------------------------------------------------
    @work(thread=True, exclusive=True, group="versions")
    def load_versions(self) -> None:
        try:
            data = self.service.versions()
        except Exception as exc:
            self.call_from_thread(self._versions_failed, str(exc))
        else:
            self.call_from_thread(self._versions_loaded, data)

    def _versions_failed(self, message: str) -> None:
        self.query_one("#versions-status", Static).update(f"[#f85149]版本清单加载失败：{message}[/]")

    def _versions_loaded(self, data: dict) -> None:
        self._versions_ready = True
        self._all_versions = list(data.get("versions") or [])
        self._populate_versions()
        self._populate_content_versions()
        self.query_one("#versions-status", Static).update(
            f"共 {len(self._all_versions)} 个版本；回车选择，安装会自动补齐依赖与 Java。"
        )

    def _filtered_versions(self) -> list[dict[str, Any]]:
        query = self.query_one("#version-search", Input).value.strip().lower()
        kind = self.query_one("#version-filter", Select).value
        installed_only = kind == "installed"
        rows = []
        for row in self._all_versions:
            if query and query not in row["id"].lower():
                continue
            if installed_only and row["id"] not in self._installed_ids:
                continue
            if kind in ("release", "snapshot") and row.get("type") != kind:
                continue
            rows.append(row)
        return rows

    def _populate_versions(self) -> None:
        rows = self._filtered_versions()
        table = self.query_one("#versions-table", DataTable)
        table.clear()
        for row in rows[:800]:
            installed = row["id"] in self._installed_ids
            table.add_row(
                row["id"],
                {"release": "正式版", "snapshot": "快照"}.get(row.get("type"), row.get("type", "")),
                str(row.get("release_time", ""))[:10],
                "已安装" if installed else "未安装",
                key=row["id"],
            )
        self.query_one("#versions-status", Static).update(
            f"显示 {min(len(rows), 800)} / {len(self._all_versions)} 个版本"
            + ("（搜索结果已截断到 800 条）" if len(rows) > 800 else "")
        )

    def _selected_version_id(self) -> str:
        table = self.query_one("#versions-table", DataTable)
        if table.cursor_row < 0:
            return ""
        row = table.get_row_at(table.cursor_row)
        return str(row[0]) if row else ""

    # ------------------------------------------------------------------
    def _install(self, version_id: str) -> None:
        if not version_id:
            self.notify("请先选择一个版本", severity="warning")
            return
        if self._installing:
            self.notify("已有安装任务在运行", severity="warning")
            return
        self._installing = True
        self._install_cancel = threading.Event()
        self.query_one(TabbedContent).active = "downloads"
        self.query_one("#download-status", Static).update(f"[#58a6ff]正在安装 {version_id}…[/]")
        self.query_one("#download-progress", ProgressBar).update(total=100, progress=0)
        self.query_one("#download-cancel", Button).disabled = False
        self.query_one("#download-log", RichLog).write(f"[bold]开始安装 Minecraft {version_id}[/]")
        self.install_worker(version_id)

    @work(thread=True, exclusive=True, group="install")
    def install_worker(self, version_id: str) -> None:
        try:
            result = self.service.install(
                version_id,
                callback=lambda event: self.call_from_thread(self._on_install_progress, event),
                log_callback=lambda message: self.call_from_thread(self._on_install_log, message),
                cancel_event=self._install_cancel,
            )
        except Exception as exc:
            cancelled = bool(self._install_cancel and self._install_cancel.is_set())
            self.call_from_thread(self._install_done, False, "已取消" if cancelled else str(exc))
        else:
            self.call_from_thread(self._install_done, True, str(result.get("id") or version_id))

    def _on_install_progress(self, event: dict) -> None:
        total = float(event.get("total") or 0)
        done = float(event.get("done") or 0)
        percent = float(event.get("percent") or 0)
        bar = self.query_one("#download-progress", ProgressBar)
        bar.update(total=100, progress=percent)
        label = str(event.get("label") or "下载")
        speed = float(event.get("speed") or 0)
        self.query_one("#download-status", Static).update(
            f"{label} · {percent:.0f}%" + (f" · {speed / 1024 / 1024:.1f} MB/s" if speed else "")
        )

    def _on_install_log(self, message: str) -> None:
        if message:
            self.query_one("#download-log", RichLog).write(message)

    def _install_done(self, ok: bool, message: str) -> None:
        self._installing = False
        self._install_cancel = None
        button = self.query_one("#download-cancel", Button)
        button.disabled = True
        if ok:
            self.query_one("#download-progress", ProgressBar).update(total=100, progress=100)
            self.query_one("#download-status", Static).update(f"[#3fb950]安装完成：Minecraft {message}[/]")
            self.query_one("#download-log", RichLog).write(f"[#3fb950][+] Minecraft {message} 安装完成[/]")
            self.refresh_dashboard()
            self._populate_versions()
            self.notify(f"Minecraft {message} 安装完成", severity="information")
        else:
            self.query_one("#download-status", Static).update(f"[#f85149]安装失败：{message}[/]")
            self.query_one("#download-log", RichLog).write(f"[#f85149][!] {message}[/]")
            self.notify(message, severity="error")

    # ------------------------------------------------------------------
    def _launch(self, version_id: str) -> None:
        if not version_id:
            self.notify("请先选择一个版本", severity="warning")
            return
        if self._game_worker is not None:
            self.notify("游戏已在运行", severity="warning")
            return
        if version_id not in self._installed_ids:
            self.notify("这个版本还没有安装完整", severity="warning")
            return
        self._game_worker = self.launch_worker(version_id)

    @work(thread=True, exclusive=True, group="launch")
    def launch_worker(self, version_id: str) -> None:
        try:
            result = self.service.launch(
                version_id,
                memory_mb=self.service.settings().get("memory_mb"),
                java_path=self.service.settings().get("java_path") or None,
                callback=lambda event: self.call_from_thread(self._on_launch_progress, event),
                on_started=lambda pid: self.call_from_thread(self._on_game_started, pid),
            )
        except Exception as exc:
            self.call_from_thread(self._launch_failed, str(exc))
        else:
            self.call_from_thread(self._game_finished, result.get("exit_code", 0))

    def _on_launch_progress(self, event: dict) -> None:
        label = str(event.get("label") or "准备启动")
        self.query_one("#download-status", Static).update(label)

    def _on_game_started(self, pid: int) -> None:
        self.query_one("#download-status", Static).update(f"[#3fb950]游戏运行中，PID {pid}[/]")
        self.notify(f"游戏已启动，PID {pid}", severity="information")

    def _game_finished(self, code: int) -> None:
        self._game_worker = None
        self.query_one("#download-status", Static).update(f"游戏已退出，代码 {code}")

    def _launch_failed(self, message: str) -> None:
        self._game_worker = None
        self.notify(f"启动失败：{message}", severity="error")

    # ------------------------------------------------------------------
    def _login(self) -> None:
        if self._login_cancel is not None:
            self.notify("登录流程已在进行中", severity="warning")
            return
        self._login_cancel = threading.Event()
        self.query_one("#account-log", RichLog).write("[bold]开始微软设备码登录…[/]")
        self.login_worker()

    @work(thread=True, exclusive=True, group="login")
    def login_worker(self) -> None:
        try:
            account = self.service.login(
                open_browser=True,
                on_code=lambda data: self.call_from_thread(self._show_device_code, data),
                on_status=lambda status: self.call_from_thread(self._login_status, status),
                cancel_event=self._login_cancel,
            )
        except Exception as exc:
            self.call_from_thread(self._login_failed, str(exc))
        else:
            self.call_from_thread(self._login_success, account)

    def _show_device_code(self, data: dict) -> None:
        code = data.get("user_code", "")
        url = data.get("verification_uri", "https://microsoft.com/link")
        self.query_one("#account-log", RichLog).write(
            f"[bold #58a6ff]浏览器打开：[/]{url}\n[bold #58a6ff]输入代码：[/][bold]{code}[/]"
        )
        self.query_one("#account-detail", Static).update(
            f"[bold #58a6ff]等待微软授权[/]\n\n访问 {url}\n输入设备码 [bold]{code}[/]"
        )

    def _login_status(self, status: str) -> None:
        texts = {
            "waiting": "等待浏览器授权…",
            "authorized": "授权成功，正在获取 Minecraft 档案…",
            "authenticating": "正在验证 Xbox / Minecraft 档案…",
        }
        if status in texts:
            self.query_one("#account-log", RichLog).write(texts[status])

    def _login_success(self, account: dict) -> None:
        self._login_cancel = None
        self.query_one("#account-log", RichLog).write(
            f"[#3fb950][+] 登录成功：{account.get('name')}[/]"
        )
        self.refresh_account()
        self.refresh_accounts()
        self.refresh_dashboard()
        self.notify(f"欢迎，{account.get('name')}", severity="information")

    def _login_failed(self, message: str) -> None:
        self._login_cancel = None
        self.query_one("#account-log", RichLog).write(f"[#f85149][!] 登录失败：{message}[/]")
        self.notify("登录失败", severity="error")

    # ------------------------------------------------------------------
    def _save_settings(self) -> None:
        try:
            memory = int(self.query_one("#memory-input", Input).value or "4096")
            values = {
                "memory_mb": memory,
                "game_dir": self.query_one("#game-dir-input", Input).value.strip(),
                "java_path": self.query_one("#java-input", Input).value.strip(),
                "theme": self.query_one("#theme-select", Select).value,
                "isolate_versions": self.query_one("#isolate-switch", Switch).value,
            }
            self.service.save_settings(values)
        except Exception as exc:
            self.query_one("#settings-status", Static).update(f"[#f85149]{exc}[/]")
            self.notify("设置保存失败", severity="error")
            return
        self.query_one("#settings-status", Static).update("[#3fb950]设置已保存。[/]")
        self.refresh_dashboard()
        self.refresh_instances()
        self.notify("设置已保存", severity="information")

    def _apply_offline(self) -> None:
        name = self.query_one("#offline-name", Input).value.strip()
        try:
            self.service.add_offline_account(name)
            self.service.switch_account(name)
        except Exception as exc:
            self.notify(str(exc), severity="error")
            return
        self.refresh_account()
        self.refresh_accounts()
        self.refresh_dashboard()
        self.notify(f"已切换离线账号：{name}", severity="information")

    def _switch_account(self) -> None:
        name = self._selected_account_name()
        if not name:
            self.notify("请先在列表中选择一个账号", severity="warning")
            return
        try:
            self.service.switch_account(name)
        except Exception as exc:
            self.notify(str(exc), severity="error")
            return
        self.refresh_account()
        self.refresh_accounts()
        self.refresh_dashboard()
        self.notify(f"已切换到 {name}", severity="information")

    def _remove_account(self) -> None:
        name = self._selected_account_name()
        if not name:
            self.notify("请先在列表中选择一个账号", severity="warning")
            return
        try:
            self.service.remove_offline_account(name)
        except Exception as exc:
            self.notify(str(exc), severity="error")
            return
        self.refresh_account()
        self.refresh_accounts()
        self.refresh_dashboard()
        self.notify(f"已删除账号 {name}", severity="information")

    def _open_instance_dir(self) -> None:
        version_id = self._selected_instance_id()
        if not version_id:
            self.notify("请先在列表中选择一个版本", severity="warning")
            return
        path = self.service.paths.instance_dir(version_id)
        path.mkdir(parents=True, exist_ok=True)
        for sub in ("mods", "saves", "resourcepacks", "shaderpacks", "config"):
            (path / sub).mkdir(exist_ok=True)
        self.notify(f"实例目录已就绪：{path}", severity="information")
        self.refresh_instances()

    def _uninstall(self, version_id: str) -> None:
        if not version_id:
            self.notify("请先选择一个版本", severity="warning")
            return
        if version_id not in self._installed_ids:
            self.notify("这个版本还没有安装", severity="warning")
            return

        def handle(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                result = self.service.uninstall(version_id)
            except Exception as exc:
                self.notify(f"卸载失败：{exc}", severity="error")
                return
            self.refresh_dashboard()
            self.refresh_instances()
            self._populate_versions()
            self._populate_content_versions()
            self.notify(
                f"已卸载 {version_id}，释放 {result.get('freed_text') or '0 B'}",
                severity="information",
            )

        self.push_screen(
            ConfirmScreen(
                "卸载版本",
                f"删除 [bold]{version_id}[/] 及其隔离目录（包含存档与 Mod），此操作无法撤销。",
                "删除",
            ),
            handle,
        )

    # ------------------------------------------------------------------
    # 模组 / 资源包
    # ------------------------------------------------------------------
    def _content_kind(self) -> str:
        value = self.query_one("#content-kind", Select).value
        return "resourcepack" if value == "resourcepack" else "mod"

    def _content_game_version(self) -> str | None:
        value = self.query_one("#content-game", Select).value
        if value is Select.BLANK:
            return None
        return str(value)

    def _content_source(self) -> str:
        value = self.query_one("#content-source", Select).value
        return "curseforge" if value == "curseforge" else "modrinth"

    def _content_loader(self) -> str | None:
        if self._content_kind() != "mod":
            return None
        value = self.query_one("#content-loader", Select).value
        return None if value is Select.BLANK else str(value)

    def _populate_content_versions(self) -> None:
        """内容页的游戏版本下拉框只列已安装版本。"""
        select = self.query_one("#content-game", Select)
        options = [
            (row["id"], row["id"])
            for row in self._all_versions
            if row.get("installed") or row["id"] in self._installed_ids
        ]
        current = select.value if select.value is not Select.BLANK else None
        select.set_options(options)
        if current and any(value == current for _, value in options):
            select.value = current
        elif options:
            select.value = options[0][1]

    @work(thread=True, exclusive=True, group="content-search")
    def search_content_worker(self, query: str, kind: str, game_version: str | None, loader: str | None, source: str) -> None:
        try:
            data = self.service.search_content(
                query,
                project_type=kind,
                game_version=game_version,
                loader=loader,
                limit=30,
                source=source,
            )
        except Exception as exc:
            self.call_from_thread(self._content_search_failed, str(exc))
        else:
            self.call_from_thread(self._content_search_done, data, source)

    def _content_search_failed(self, message: str) -> None:
        self.query_one("#content-status", Static).update(f"[#f85149]搜索失败：{message}[/]")
        self.notify(f"搜索失败：{message}", severity="error")

    def _content_search_done(self, data: dict, source: str) -> None:
        self._content_hits = list(data.get("hits") or [])
        for hit in self._content_hits:
            hit["source"] = source
        table = self.query_one("#content-table", DataTable)
        table.clear()
        for hit in self._content_hits:
            table.add_row(
                hit.get("title") or hit.get("slug") or "未知",
                hit.get("author") or "-",
                f"{int(hit.get('downloads') or 0):,}",
                str(hit.get("id") or ""),
                key=str(hit.get("id") or hit.get("slug") or ""),
            )
        kind_label = "资源包" if self._content_kind() == "resourcepack" else "模组"
        self.query_one("#content-status", Static).update(
            f"共 {data.get('total', len(self._content_hits))} 个{kind_label}，显示前 {len(self._content_hits)} 个。"
            "选中一行查看可用文件。"
        )

    def _search_content(self) -> None:
        query = self.query_one("#content-search", Input).value.strip()
        if not query:
            self.notify("请输入搜索关键词", severity="warning")
            return
        kind = self._content_kind()
        source = self._content_source()
        if source == "curseforge" and not self.service.curseforge_key():
            self.notify("CurseForge 需要先在设置里填写 API Key", severity="warning")
            return
        game_version = self._content_game_version()
        if not game_version:
            self.notify("请先在「已安装版本」里选择一个版本", severity="warning")
            return
        self.query_one("#content-status", Static).update(f"正在搜索 {source} …")
        self.search_content_worker(query, kind, game_version, self._content_loader(), source)

    def _selected_content(self) -> dict[str, Any] | None:
        table = self.query_one("#content-table", DataTable)
        if table.cursor_row < 0:
            return None
        try:
            row = table.get_row_at(table.cursor_row)
        except Exception:
            return None
        if not row:
            return None
        project_id = str(row[3])
        return next((h for h in getattr(self, "_content_hits", []) if str(h.get("id")) == project_id), None)

    @work(thread=True, exclusive=True, group="content-files")
    def load_content_files(self, hit: dict, kind: str, game_version: str | None, loader: str | None, source: str) -> None:
        try:
            versions = self.service.content_versions(
                str(hit.get("id")),
                project_type=kind,
                game_version=game_version,
                loader=loader,
                source=source,
            )
        except Exception as exc:
            self.call_from_thread(self.notify, f"读取文件列表失败：{exc}", severity="error")
        else:
            self.call_from_thread(self._content_files_loaded, versions)

    def _content_files_loaded(self, versions: list[dict[str, Any]]) -> None:
        self._content_files = versions
        table = self.query_one("#content-files", DataTable)
        table.clear()
        for index, version in enumerate(versions):
            label = str(version.get("name") or version.get("version_number") or "")
            if version.get("recommended"):
                label = f"★ {label}"
            table.add_row(
                label,
                RELEASE_LABELS.get(str(version.get("release_type")), "正式版"),
                ", ".join(version.get("game_versions") or []) or "—",
                str(version.get("date_published") or "")[:10] or "—",
                key=str(index),
            )
        if versions:
            table.move_cursor(row=0)
            self.query_one("#content-status", Static).update(
                f"共 {len(versions)} 个文件，第一行为推荐版本；选中后点「安装选中文件」。"
            )
        else:
            self.query_one("#content-status", Static).update("没有匹配的文件，换个版本或加载器试试。")

    @work(thread=True, exclusive=True, group="content-install")
    def install_content_worker(
        self,
        hit: dict,
        kind: str,
        game_version: str | None,
        loader: str | None,
        chosen: dict[str, Any],
        source: str,
    ) -> None:
        title = hit.get("title") or hit.get("id")
        self.call_from_thread(
            self.query_one("#content-status", Static).update,
            f"正在安装 {title} …",
        )
        self.call_from_thread(self._content_task_started, title, kind)
        try:
            result = self.service.install_content(
                str(hit.get("id")),
                project_type=kind,
                game_version=game_version,
                loader=loader,
                version_id=self._content_game_version(),
                chosen_version=chosen,
                source=source,
                log_callback=lambda m: self.call_from_thread(self._content_task_log, m),
                callback=lambda e: self.call_from_thread(self._content_task_progress, e),
            )
        except Exception as exc:
            self.call_from_thread(self._content_install_failed, title, str(exc))
        else:
            self.call_from_thread(self._content_install_done, title, result)

    def _content_task_started(self, title: str, kind: str) -> None:
        self._content_installing = True
        self.query_one("#download-cancel", Button).disabled = False
        kind_label = "资源包" if kind == "resourcepack" else "模组"
        self.query_one("#download-status", Static).update(f"正在安装{kind_label}：{title}")
        log = self.query_one("#download-log", RichLog)
        log.write(f"[bold #58a6ff]开始安装{kind_label}[/] {title}")

    def _content_task_progress(self, event: dict) -> None:
        bar = self.query_one("#download-progress", ProgressBar)
        bar.update(progress=float(event.get("percent") or 0))

    def _content_task_log(self, message: str) -> None:
        self.query_one("#download-log", RichLog).write(message)

    def _content_install_done(self, title: str, result: dict) -> None:
        self._content_installing = False
        self.query_one("#download-cancel", Button).disabled = True
        files = len(result.get("files") or [])
        self.query_one("#download-status", Static).update(
            f"[#3fb950]{title} 安装完成，共 {files} 个文件[/]"
        )
        self.query_one("#content-status", Static).update(f"[#3fb950]{title} 安装完成（{files} 个文件）[/]")
        self.notify(f"{title} 已安装到 {result.get('dir')}", severity="information")

    def _content_install_failed(self, title: str, message: str) -> None:
        self._content_installing = False
        self.query_one("#download-cancel", Button).disabled = True
        self.query_one("#download-status", Static).update(f"[#f85149]{title} 安装失败：{message}[/]")
        self.query_one("#content-status", Static).update(f"[#f85149]安装失败：{message}[/]")
        self.notify(f"安装失败：{message}", severity="error")

    def _install_selected_content(self) -> None:
        hit = self._selected_content()
        if not hit:
            self.notify("请先在搜索结果中选择一个项目", severity="warning")
            return
        files = getattr(self, "_content_files", [])
        table = self.query_one("#content-files", DataTable)
        if not files or table.cursor_row < 0:
            self.notify("请先在下方文件列表中选择一个版本", severity="warning")
            return
        if table.cursor_row >= len(files):
            return
        chosen = files[table.cursor_row]
        self.install_content_worker(
            hit,
            self._content_kind(),
            self._content_game_version(),
            self._content_loader(),
            chosen,
            self._content_source(),
        )

    def _open_content_dir(self) -> None:
        kind = self._content_kind()
        path = self.service.content_dir(kind, self._content_game_version())
        path.mkdir(parents=True, exist_ok=True)
        self.notify(f"内容目录：{path}", severity="information")

    # ------------------------------------------------------------------
    def action_tab(self, pane_id: str) -> None:
        self.query_one(TabbedContent).active = pane_id

    def action_refresh(self) -> None:
        self.refresh_dashboard()
        self.refresh_instances()
        self.refresh_accounts()
        self.load_versions()

    def action_install(self) -> None:
        version_id = self._selected_version_id() or self._dash_version
        self._install(version_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "dash-launch":
            self._launch(self._dash_version)
        elif button_id == "dash-refresh":
            self.action_refresh()
        elif button_id == "dash-browse":
            self.action_tab("versions")
        elif button_id == "versions-refresh":
            self.load_versions()
        elif button_id == "versions-action":
            version_id = self._selected_version_id()
            if version_id in self._installed_ids:
                self._launch(version_id)
            else:
                self._install(version_id)
        elif button_id == "versions-uninstall":
            self._uninstall(self._selected_version_id())
        elif button_id == "content-search-btn":
            self._search_content()
        elif button_id == "content-install":
            self._install_selected_content()
        elif button_id == "content-open":
            self._open_content_dir()
        elif button_id == "instance-refresh":
            self.refresh_instances()
        elif button_id == "instance-open":
            self._open_instance_dir()
        elif button_id == "account-switch":
            self._switch_account()
        elif button_id == "account-remove":
            self._remove_account()
        elif button_id == "download-cancel":
            if self._install_cancel is not None:
                self._install_cancel.set()
                self.query_one("#download-status", Static).update("[#d29922]正在取消…[/]")
                self.query_one("#download-cancel", Button).disabled = True
        elif button_id == "download-clear":
            self.query_one("#download-log", RichLog).clear()
        elif button_id == "login":
            self._login()
        elif button_id == "logout":
            self.service.logout()
            self.refresh_account()
            self.refresh_accounts()
            self.refresh_dashboard()
            self.notify("已退出微软账号", severity="information")
        elif button_id == "offline-apply":
            self._apply_offline()
        elif button_id == "save-settings":
            self._save_settings()
        elif button_id == "reload-settings":
            self.load_settings()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "version-search":
            self._populate_versions()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "content-search":
            self._search_content()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "dash-version" and event.value is not Select.BLANK:
            self._dash_version = str(event.value)
        elif event.select.id == "version-filter":
            self._populate_versions()
        elif event.select.id == "content-kind":
            is_mod = self._content_kind() == "mod"
            self.query_one("#content-loader", Select).disabled = not is_mod

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "versions-table":
            row = event.data_table.get_row_at(event.cursor_row)
            if row:
                self._selected_version = str(row[0])
        elif event.data_table.id == "content-table":
            self._load_files_for_selected()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "versions-table":
            row = event.data_table.get_row_at(event.cursor_row)
            if row:
                self._selected_version = str(row[0])
        elif event.data_table.id == "content-table":
            self._load_files_for_selected()

    def _load_files_for_selected(self) -> None:
        hit = self._selected_content()
        if not hit:
            return
        game_version = self._content_game_version()
        if not game_version:
            return
        self.load_content_files(
            hit,
            self._content_kind(),
            game_version,
            self._content_loader(),
            self._content_source(),
        )


def main(game_dir: str | Path | None = None, config_dir: str | Path | None = None) -> int:
    app = MCLTuiApp(game_dir, config_dir)
    app.run()
    return 0
