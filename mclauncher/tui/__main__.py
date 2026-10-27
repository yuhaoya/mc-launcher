from __future__ import annotations

import argparse
import sys

from .app import MCLTuiApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcl-tui", description="MCL Studio TUI - 终端 Minecraft 启动器")
    parser.add_argument("--game-dir", default=None, help="游戏目录")
    parser.add_argument("--config-dir", default=None, help="配置目录")
    args = parser.parse_args(argv)
    app = MCLTuiApp(args.game_dir, args.config_dir)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
