from __future__ import annotations

import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QThreadPool, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
)

from ..services import LauncherService
from .pages.account import AccountPage, LoginDialog
from .pages.downloads import DownloadsPage
from .pages.home import HomePage
from .pages.settings import SettingsPage
from .pages.versions import VersionsPage
from .theme import apply_theme
from .workers import Worker


class MainWindow(FluentWindow):
    def __init__(self, service: LauncherService):
        super().__init__()
        self.service = service
        self._workers: set[Worker] = set()
        self._install_task: dict | None = None
        self._game_worker: Worker | None = None
        self._game_pid = 0
        self.setWindowTitle("MCL Studio")
        self.resize(1240, 820)
        self.setMinimumSize(1060, 700)
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            pass

        QThreadPool.globalInstance().setMaxThreadCount(12)

        self.home_page = HomePage(service, self)
        self.versions_page = VersionsPage(service, self)
        self.downloads_page = DownloadsPage(service, self)
        self.account_page = AccountPage(service, self)
        self.settings_page = SettingsPage(service, self)

        self.addSubInterface(self.home_page, FIF.HOME, "主页")
        self.addSubInterface(self.versions_page, FIF.LIBRARY, "版本")
        self.addSubInterface(self.downloads_page, FIF.DOWNLOAD, "下载")
        self.addSubInterface(self.account_page, FIF.PEOPLE, "账号")
        self.addSubInterface(self.settings_page, FIF.SETTING, "设置", NavigationItemPosition.BOTTOM)

        self.navigationInterface.setExpandWidth(214)
        self.navigationInterface.expand(useAni=False)

        self.home_page.browseRequested.connect(lambda: self.switchTo(self.versions_page))
        self.home_page.manageRequested.connect(lambda: self.switchTo(self.versions_page))
        self.home_page.playRequested.connect(self._launch)

        self.versions_page.installRequested.connect(self._start_install)
        self.versions_page.installFabricRequested.connect(lambda vid: self._start_install(vid, "fabric"))
        self.versions_page.installForgeRequested.connect(lambda vid: self._start_install(vid, "forge"))
        self.versions_page.launchRequested.connect(self._launch)
        self.versions_page.openFolderRequested.connect(self._open_version_folder)

        self.downloads_page.cancelRequested.connect(self._cancel_install)

        self.account_page.loginRequested.connect(self._login)
        self.account_page.logoutRequested.connect(self._logout)
        self.account_page.offlineRequested.connect(self._set_offline)

        self.settings_page.saveRequested.connect(self._save_settings)

        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self._refresh_all()

    # ------------------------------------------------------------------
    def switchTo(self, page) -> None:
        if page is self.stackedWidget.currentWidget():
            return
        # 直接使用父类的实现，它会自动处理好顺序和动画
        super().switchTo(page)

    def _on_page_changed(self, index: int) -> None:
        page = self.stackedWidget.widget(index)
        if page is self.versions_page:
            self.versions_page.ensure_loaded()
        elif page is self.settings_page:
            self.settings_page.refresh()
        elif page is self.account_page:
            self.account_page.refresh()
        elif page is self.home_page:
            self.home_page.refresh()

    def _refresh_all(self) -> None:
        self.home_page.refresh()
        self.account_page.refresh()
        self.settings_page.refresh()

    # ------------------------------------------------------------------
    def _start_install(self, version_id: str, loader: str = "vanilla") -> None:
        print(f"DEBUG: 收到安装请求 version={version_id}, loader={loader}")
        if self._install_task is not None:
            InfoBar.info("已有安装任务", "请等待当前安装完成。", parent=self, position=InfoBarPosition.TOP_RIGHT)
            self.switchTo(self.downloads_page)
            return

        task_id = uuid.uuid4().hex[:8]
        cancel_event = threading.Event()

        # 根据加载器类型生成显示的标题
        loader_name = "原版"
        if loader == "fabric":
            loader_name = "Fabric"
        elif loader == "forge":
            loader_name = "Forge"
        display_name = f"{version_id} ({loader_name})"
        card = self.downloads_page.add_task(task_id, display_name)
        self.switchTo(self.downloads_page)

        # 根据加载器类型选择要执行的方法
        if loader == "fabric":
            worker_func = lambda w: self.service.install_fabric(
                version_id,
                callback=w.signals.progress.emit,
                log_callback=w.signals.log.emit  # 如果你刚才的 install_fabric 里加了 log_callback，记得改一下
            )
        elif loader == "forge":
            worker_func = lambda w: self.service.install_forge(
                version_id,
                callback=w.signals.progress.emit,
                log_callback=w.signals.log.emit,
                cancel_event=cancel_event,
            )
        else:
            worker_func = lambda w: self.service.install(
                version_id,
                with_java=True,
                callback=w.signals.progress.emit,
                log_callback=w.signals.log.emit,
                cancel_event=cancel_event,
            )

        worker = Worker(worker_func)
        self._install_task = {
            "id": task_id,
            "version": version_id,
            "cancel": cancel_event,
            "worker": worker,
            "card": card,
        }
        self._workers.add(worker)

        # 信号连接
        worker.signals.progress.connect(lambda event: self.downloads_page.update_progress(task_id, event))
        worker.signals.log.connect(self.downloads_page.append_log)
        worker.signals.result.connect(lambda data: self._install_finished(task_id, data))
        worker.signals.error.connect(lambda message: self._install_failed(task_id, message))
        worker.signals.finished.connect(lambda: self._install_worker_finished(worker))

        QThreadPool.globalInstance().start(worker)

    def _install_finished(self, task_id: str, data: dict) -> None:
        self.downloads_page.finish_task(task_id, True, "安装完成")
        self._install_task = None
        self.home_page.refresh()
        self.versions_page.refresh_installed()
        InfoBar.success(
            "安装完成",
            f"Minecraft {data.get('id')} 已准备好，可以启动。",
            parent=self,
            duration=2500,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _install_failed(self, task_id: str, message: str) -> None:
        task = self._install_task
        cancelled = bool(task and task["cancel"].is_set()) or "取消" in message
        self.downloads_page.finish_task(task_id, False, "已取消" if cancelled else message)
        self._install_task = None
        if cancelled:
            InfoBar.warning("安装已取消", f"Minecraft {task['version']} 未安装完成。", parent=self)
        else:
            InfoBar.error("安装失败", message, parent=self, duration=5000)

    def _install_worker_finished(self, worker: Worker) -> None:
        self._workers.discard(worker)

    def _cancel_install(self, task_id: str) -> None:
        task = self._install_task
        if task and task["id"] == task_id:
            task["cancel"].set()
            card = task["card"]
            if card is not None:
                card.status_label.setText("正在取消…")
                card.cancel_button.setEnabled(False)
            InfoBar.info("正在取消", "当前文件下载完成后会停止。", parent=self)

    # ------------------------------------------------------------------
    def _launch(self, version_id: str) -> None:
        if self._game_worker is not None:
            InfoBar.warning(
                "游戏已在运行",
                "请先关闭正在运行的游戏，再启动另一个实例。",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        settings = self.service.settings()
        print(f"DEBUG: settings is {settings}") # 👈 打印看看
        self.home_page.play_button.setEnabled(False)
        self.home_page.play_button.setText("准备启动…")

        print("DEBUG account:", self.service.account())

        def _run_launch(w):
            try:
                return self.service.launch(
                    version_id,
                    memory_mb=settings.get("memory_mb"),
                    java_path=settings.get("java_path") or None,
                    callback=w.signals.progress.emit,
                    log_callback=w.signals.log.emit,
                    on_started=w.signals.started.emit,
                )
            except AttributeError as e:
                import traceback
                traceback.print_exc()  # 这会在后台把完整的代码报错位置打印到控制台
                raise e

        worker = Worker(
            lambda w: self.service.launch(
                version_id,
                memory_mb=settings.get("memory_mb"),
                java_path=settings.get("java_path") or None,
                callback=w.signals.progress.emit,
                log_callback=w.signals.log.emit,
                on_started=w.signals.started.emit,
            )
        )


        self._game_worker = worker
        self._workers.add(worker)
        worker.signals.started.connect(self._game_started)
        worker.signals.progress.connect(self._launch_progress)
        worker.signals.result.connect(self._game_finished)
        worker.signals.error.connect(self._launch_failed)
        worker.signals.finished.connect(lambda: self._workers.discard(worker))
        QThreadPool.globalInstance().start(worker)

    def _launch_progress(self, event: dict) -> None:
        if self._game_pid:
            return
        total = int(event.get("total") or 0)
        percent = int(event.get("percent") or 0)
        if total:
            self.home_page.play_button.setText(f"准备 Java {percent}%")
        else:
            self.home_page.play_button.setText("准备启动…")

    def _game_started(self, pid: int) -> None:
        self._game_pid = pid
        self.home_page.play_button.setText("游戏运行中")
        self.home_page.play_button.setEnabled(False)
        InfoBar.success(
            "游戏已启动",
            f"进程 PID {pid}。关闭游戏后启动器会自动恢复。",
            parent=self,
            duration=3000,
        )

    def _game_finished(self, result: dict) -> None:
        code = int(result.get("exit_code") or 0)
        self._game_pid = 0
        self._game_worker = None
        self.home_page.play_button.setText("启动游戏")
        self.home_page.play_button.setEnabled(True)
        if code == 0:
            InfoBar.info("游戏已退出", "下次冒险见。", parent=self, duration=2000)
        else:
            InfoBar.warning("游戏异常退出", f"退出代码 {code}，可以查看日志排查。", parent=self)

    def _launch_failed(self, message: str) -> None:
        self._game_pid = 0
        self._game_worker = None
        self.home_page.play_button.setText("启动游戏")
        self.home_page.play_button.setEnabled(True)
        InfoBar.error("启动失败", message, parent=self, duration=6000)

    # ------------------------------------------------------------------
    def _login(self) -> None:
        account = self.service.account()
        if account and not account["offline"]:
            InfoBar.info("已经登录", f"当前账号：{account['name']}", parent=self)
            return
        dialog = LoginDialog(self.service, self)
        result = dialog.exec()
        if dialog.account:
            self._refresh_all()
            self.versions_page.refresh_installed()
            InfoBar.success("登录成功", f"欢迎，{dialog.account['name']}。", parent=self, duration=2500)

    def _logout(self) -> None:
        self.service.logout()
        self._refresh_all()
        InfoBar.success("已退出微软账号", "已切换回离线账号。", parent=self)

    def _set_offline(self, name: str) -> None:
        try:
            self.service.add_offline_account(name)  # ① 持久化到 offline_names
            self.service.switch_account(name)  # ② 设为当前
        except Exception as exc:
            InfoBar.error("离线用户名无效", str(exc), parent=self)
            return
        self._refresh_all()
        self.versions_page.refresh_installed()
        InfoBar.success("已切换离线账号", f"玩家名：{name}", parent=self)

    # ------------------------------------------------------------------
    def _save_settings(self, values: dict) -> None:
        try:
            self.service.save_settings(values)
        except Exception as exc:
            InfoBar.error("保存失败", str(exc), parent=self)
            return
        apply_theme(self.service.settings()["theme"], self.service.settings()["accent"])
        self.settings_page.refresh()
        self.home_page.refresh()
        self.account_page.refresh()
        InfoBar.success(
            "设置已保存",
            "部分自定义颜色会在下次启动时完全生效。",
            parent=self,
            duration=2500,
        )

    def _open_version_folder(self, version_id: str) -> None:
        path = self.service.paths.version_dir(version_id)
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._install_task is not None:
            self._install_task["cancel"].set()
        super().closeEvent(event)
