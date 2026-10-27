from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__
from .auth import DEFAULT_CLIENT_ID, cached_profile, get_account, login, logout, offline_account
from .config import Config
from .errors import LauncherError
from .installer import Installer, is_installed
from .java import (
    detect_java_major,
    ensure_java,
    find_java,
    install_runtime,
    list_javas,
)
from .launcher import LaunchOptions, launch
from .paths import Paths, default_game_dir
from .util import human_size, parse_memory_mb, read_json
from .versions import VersionRepository

TYPE_NAMES = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "远古 beta",
    "old_alpha": "远古 alpha",
}


def _add_dir_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dir",
        dest="dir_cmd",
        metavar="目录",
        default=None,
        help="游戏目录（默认读取配置，否则使用 %%APPDATA%%\\.minecraft）",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcl",
        description="mclauncher - 轻量 Minecraft 命令行启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  mcl versions                 查看可安装版本\n"
            "  mcl install 1.20.1           下载并安装 1.20.1\n"
            "  mcl login                    微软账号设备码登录\n"
            "  mcl launch 1.20.1            用正版账号启动\n"
            "  mcl launch 1.20.1 --offline Steve   离线启动\n"
            "  mcl launch 1.20.1 --dry-run  只打印启动命令\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"mclauncher {__version__}")
    parser.add_argument("--dir", dest="game_dir", metavar="目录", default=None, help="游戏目录")
    parser.add_argument("--config-dir", dest="config_dir", metavar="目录", default=None, help="配置目录")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<命令>")

    p = sub.add_parser("login", help="使用微软账号登录")
    p.add_argument("--client-id", default=None, help=f"Azure 应用客户端 ID（默认 {DEFAULT_CLIENT_ID}）")
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    sub.add_parser("logout", help="退出微软账号（清除本地 token）")

    p = sub.add_parser("whoami", help="查看当前登录的账号")
    p.add_argument("--offline", metavar="名字", default=None, help="查看离线账号的 UUID")

    p = sub.add_parser("versions", help="列出 Mojang 可安装版本")
    _add_dir_option(p)
    p.add_argument("--type", choices=["all", "release", "snapshot"], default="release", help="版本类型（默认 release）")
    p.add_argument("--limit", type=int, default=20, help="显示数量（默认 20，0 表示全部）")
    p.add_argument("--force", action="store_true", help="强制刷新版本清单")

    p = sub.add_parser("install", help="下载并安装指定版本")
    _add_dir_option(p)
    p.add_argument("version", help="版本号，或 latest / latest-snapshot")
    p.add_argument("--skip-assets", action="store_true", help="跳过资源文件（不推荐）")
    p.add_argument("--with-java", action="store_true", help="同时安装匹配的 Java 运行时")
    p.add_argument("--force", action="store_true", help="强制重新读取版本 JSON")
    p.add_argument("--workers", type=int, default=16, help="并发下载线程数（默认 16）")

    p = sub.add_parser("list", help="列出已安装版本")
    _add_dir_option(p)

    p = sub.add_parser("launch", help="启动游戏")
    _add_dir_option(p)
    p.add_argument("version", help="版本号，或 latest / latest-snapshot")
    p.add_argument("--offline", metavar="名字", default=None, help="离线模式，使用指定用户名")
    p.add_argument("--demo", action="store_true", help="启动试玩模式")
    p.add_argument("--width", type=int, default=None, help="窗口宽度（需与 --height 一起使用）")
    p.add_argument("--height", type=int, default=None, help="窗口高度")
    p.add_argument("--memory", default=None, help="最大内存，如 4096 / 4G（默认 4096）")
    p.add_argument("--java", metavar="路径", default=None, help="手动指定 java.exe")
    p.add_argument("--jvm-arg", action="append", default=[], help="追加 JVM 参数（可多次）")
    p.add_argument("--game-arg", action="append", default=[], help="追加游戏参数（可多次）")
    p.add_argument("--no-install", action="store_true", help="未安装时不自动下载")
    p.add_argument("--no-auto-java", action="store_true", help="缺少 Java 时不自动下载")
    p.add_argument("--dry-run", action="store_true", help="只打印启动命令，不实际启动")
    p.add_argument("--workers", type=int, default=16, help="自动安装时的下载线程数（默认 16）")

    p = sub.add_parser("java", help="查看或安装 Java 运行时")
    _add_dir_option(p)
    p.add_argument("--install", metavar="版本", default=None, help="安装运行时的主版本号（如 21）或组件名")
    p.add_argument("--list", action="store_true", help="仅列出检测到的 Java")

    p = sub.add_parser("dir", help="显示各目录位置")
    _add_dir_option(p)

    return parser


# ----------------------------------------------------------------------
def make_context(args: argparse.Namespace) -> tuple[Paths, Config]:
    config = Config(Path(args.config_dir).expanduser() if getattr(args, "config_dir", None) else None)
    game_dir = (
        getattr(args, "dir_cmd", None)
        or getattr(args, "game_dir", None)
        or os.environ.get("MCL_DIR")
        or config.get("game_dir")
        or default_game_dir()
    )
    return Paths(Path(game_dir).expanduser().resolve(), config.dir.resolve()), config


def _repo(args: argparse.Namespace, paths: Paths) -> VersionRepository:
    return VersionRepository(paths, sys.stdout)


def _memory(args: argparse.Namespace, config: Config) -> int:
    raw = args.memory if args.memory is not None else config.get("memory_mb") or 4096
    try:
        return parse_memory_mb(raw)
    except ValueError as exc:
        raise LauncherError(str(exc)) from exc


def _resolve_version(repo: VersionRepository, version: str) -> dict:
    return repo.resolve(version)


def cmd_versions(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    repo = _repo(args, paths)
    manifest = repo.manifest(force=args.force)
    wanted = args.type
    rows = [
        version
        for version in manifest.get("versions", [])
        if wanted == "all" or (wanted == "release" and version.get("type") == "release") or (wanted == "snapshot" and version.get("type") == "snapshot")
    ]
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        print("没有符合条件的版本")
        return 0
    print(f"{'版本':<18}{'类型':<10}{'发布时间':<12}状态")
    print("-" * 52)
    for version in rows:
        version_id = version.get("id", "")
        installed = is_installed(paths, version_id)
        release_time = (version.get("releaseTime") or "")[:10]
        print(
            f"{version_id:<18}{TYPE_NAMES.get(version.get('type'), version.get('type')):<10}"
            f"{release_time:<12}{'已安装' if installed else ''}"
        )
    print(f"\n共显示 {len(rows)} 个版本；安装: mcl install <版本>")
    return 0


def cmd_install(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    repo = _repo(args, paths)
    entry = _resolve_version(repo, args.version)
    version_id = entry["id"]
    meta = repo.meta(version_id, force=args.force)
    print(
        f"[*] Java {((meta.get('javaVersion') or {}).get('majorVersion') or 8)}，"
        f"资源约 {human_size(((meta.get('assetIndex') or {}).get('totalSize') or 0))}，"
        f"客户端 {human_size(((meta.get('downloads') or {}).get('client') or {}).get('size') or 0)}"
    )
    installer = Installer(paths, workers=max(1, min(32, args.workers)))
    installer.install(
        version_id,
        skip_assets=args.skip_assets,
        force=args.force,
        with_java=args.with_java,
    )
    return 0


def cmd_list(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    repo = _repo(args, paths)
    versions = repo.installed_versions()
    if not versions:
        print("还没有安装任何版本。先运行 `mcl versions` 查看，再 `mcl install <版本>`。")
        return 0
    print(f"{'版本':<20}{'类型':<10}{'Java':<6}{'大小':<10}资源索引")
    print("-" * 68)
    for version_id in versions:
        meta = read_json(paths.version_json(version_id), {}) or {}
        jar = paths.client_jar(version_id)
        size = jar.stat().st_size if jar.is_file() else 0
        java_version = (meta.get("javaVersion") or {}).get("majorVersion") or 8
        asset_index = (meta.get("assetIndex") or {}).get("id") or meta.get("assets") or "-"
        print(
            f"{version_id:<20}{TYPE_NAMES.get(meta.get('type'), meta.get('type', '-')):<10}"
            f"{java_version:<6}{human_size(size):<10}{asset_index}"
        )
    return 0


def _prepare_version(args: argparse.Namespace, repo: VersionRepository, paths: Paths) -> tuple[str, dict]:
    entry = _resolve_version(repo, args.version)
    version_id = entry["id"]
    if not is_installed(paths, version_id):
        if args.no_install:
            raise LauncherError(f"版本 {version_id} 尚未安装。先运行 `mcl install {version_id}`。")
        print(f"[*] 版本 {version_id} 尚未安装，先自动安装...")
        Installer(paths, workers=max(1, min(32, args.workers))).install(version_id)
    return version_id, repo.meta(version_id)


def cmd_launch(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    repo = _repo(args, paths)
    version_id, meta = _prepare_version(args, repo, paths)

    if args.offline is not None:
        account = offline_account(args.offline)
        print(f"[*] 离线账号: {account.name} ({account.uuid})")
    else:
        account = get_account(config)

    required = int((meta.get("javaVersion") or {}).get("majorVersion") or 8)
    if args.java:
        java = Path(args.java).expanduser()
        if java.is_dir():
            java = java / "bin" / ("java.exe" if os.name == "nt" else "java")
        java = java.resolve()
        if not java.is_file():
            raise LauncherError(f"指定的 Java 不存在: {java}")
        actual = detect_java_major(java)
        if actual is None:
            raise LauncherError(f"无法识别 Java 版本: {java}")
        if actual != required:
            print(f"[!] 该版本建议 Java {required}，你将使用 Java {actual}")
    elif args.dry_run:
        found = find_java(paths, required, config.get("java_path"))
        if found:
            java = found[0]
            if found[1] != required:
                print(f"[!] 未找到 Java {required}，dry-run 使用 Java {found[1]}")
        else:
            java = Path("java")
            print(f"[!] 未找到 Java {required}，dry-run 命令里用 `java` 占位")
    else:
        java = ensure_java(
            meta,
            paths,
            configured=config.get("java_path"),
            allow_install=not args.no_auto_java,
        )

    memory = _memory(args, config)
    width = args.width
    height = args.height
    if (width is None) != (height is None):
        width = width or 854
        height = height or 480

    options = LaunchOptions(
        version_id=version_id,
        account=account,
        memory_mb=memory,
        width=width,
        height=height,
        demo=args.demo,
        jvm_args=list(args.jvm_arg),
        game_args=list(args.game_arg),
        dry_run=args.dry_run,
    )
    return launch(meta, paths, options, java)


def cmd_login(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    login(config, args.client_id, open_browser=not args.no_browser)
    return 0


def cmd_logout(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    logout(config)
    print("[+] 已清除本地微软账号 token")
    return 0


def cmd_whoami(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    if args.offline:
        account = offline_account(args.offline)
        print(f"离线模式: {account.name}")
        print(f"UUID    : {account.uuid}")
        return 0
    profile = cached_profile(config)
    if not profile:
        print("未登录微软账号。运行 `mcl login` 登录，或使用 `mcl launch <版本> --offline <名字>`。")
        return 0
    print(f"微软账号: {profile['name']}")
    print(f"UUID    : {profile['uuid']}")
    expires_at = float(profile.get("expires_at") or 0)
    if expires_at:
        if expires_at > time.time() + 60:
            print(f"token   : 有效至 {time.strftime('%Y-%m-%d %H:%M', time.localtime(expires_at))}")
        else:
            print("token   : 已过期，下次启动会自动刷新")
    print(f"客户端ID: {profile['client_id']}")
    return 0


def cmd_java(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    if args.install:
        value = args.install.strip()
        if value.isdigit():
            path = install_runtime(paths, major=int(value))
        else:
            path = install_runtime(paths, component=value)
        print(f"[+] Java 运行时: {path}")
        return 0

    javas = list_javas(paths, config.get("java_path"))
    if not javas:
        print("没有检测到任何 Java。可用 `mcl java --install 21` 下载 Mojang 运行时。")
        return 0
    print("检测到的 Java：")
    for path, major in javas:
        label = f"Java {major}" if major else "未知版本"
        print(f"  {label:<10} {path}")
    print("\n安装指定主版本: mcl java --install 21")
    return 0


def cmd_dir(args: argparse.Namespace, paths: Paths, config: Config) -> int:
    print(paths.describe())
    print(f"配置文件   : {paths.config_file}")
    return 0


COMMANDS = {
    "versions": cmd_versions,
    "install": cmd_install,
    "list": cmd_list,
    "launch": cmd_launch,
    "login": cmd_login,
    "logout": cmd_logout,
    "whoami": cmd_whoami,
    "java": cmd_java,
    "dir": cmd_dir,
}


def _configure_stdio() -> None:
    """Windows 终端统一使用 UTF-8，避免中文帮助/日志乱码。"""
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        paths, config = make_context(args)
        return COMMANDS[args.command](args, paths, config)
    except LauncherError as exc:
        print(f"[!] 错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[!] 已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
