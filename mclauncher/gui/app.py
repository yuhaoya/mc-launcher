from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..services import LauncherService
from .theme import apply_font, apply_theme
from .window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcl-gui", description="MCL Studio - Fluent Design 2 Minecraft 启动器")
    parser.add_argument("--game-dir", default=None, help="游戏目录")
    parser.add_argument("--config-dir", default=None, help="配置目录")
    parser.add_argument("--screenshot", default=None, help="渲染窗口并保存 PNG 后退出（测试用）")
    parser.add_argument("--page", default="home", choices=["home", "versions", "downloads", "account", "settings"])
    parser.add_argument("--version", action="version", version=f"MCL Studio {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("MCL Studio")
    app.setApplicationDisplayName("MCL Studio")
    app.setOrganizationName("mclauncher")
    apply_font(app)

    service = LauncherService(args.game_dir, args.config_dir)
    settings = service.settings()
    apply_theme(settings["theme"], settings["accent"])

    window = MainWindow(service)
    icon_path = Path(__file__).with_name("assets") / "app.png"
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    pages = {
        "home": window.home_page,
        "versions": window.versions_page,
        "downloads": window.downloads_page,
        "account": window.account_page,
        "settings": window.settings_page,
    }
    if args.page != "home":
        window.switchTo(pages[args.page])

    if args.screenshot:
        def grab() -> None:
            target = Path(args.screenshot)
            target.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(target))
            app.quit()

        QTimer.singleShot(1400, grab)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
