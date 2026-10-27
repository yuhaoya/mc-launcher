from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .auth import Account
from .errors import LauncherError
from .installer import PATTERN_LOG_SUFFIX, build_library_plan
from .paths import Paths
from .rules import build_context, is_allowed
from .util import read_json

_VAR_RE = re.compile(r"\$\{([^}]+)\}")


@dataclass
class LaunchOptions:
    version_id: str
    account: Account
    memory_mb: int = 4096
    width: int | None = None
    height: int | None = None
    demo: bool = False
    jvm_args: list[str] = field(default_factory=list)
    game_args: list[str] = field(default_factory=list)
    dry_run: bool = False
    game_dir: str | None = None


def _substitute(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise LauncherError(f"启动参数里出现无法替换的变量: ${{{key}}}")
        return values[key]

    return _VAR_RE.sub(replace, text)


def _flatten(spec: list[Any], ctx: dict[str, Any], values: dict[str, str]) -> list[str]:
    result: list[str] = []
    for item in spec:
        if isinstance(item, str):
            result.append(_substitute(item, values))
        elif isinstance(item, dict):
            if not is_allowed(item.get("rules"), ctx):
                continue
            value = item.get("value")
            if isinstance(value, str):
                result.append(_substitute(value, values))
            elif isinstance(value, list):
                result.extend(_substitute(str(entry), values) for entry in value)
    return result


def _game_assets_dir(paths: Paths, index_id: str) -> Path:
    index = read_json(paths.assets_indexes / f"{index_id}.json")
    if isinstance(index, dict):
        if index.get("virtual"):
            return paths.assets_virtual / index_id
        if index.get("map_to_resources"):
            return paths.game_dir / "resources"
    return paths.assets


def _classpath(meta: dict[str, Any], paths: Paths, ctx: dict[str, Any]) -> list[Path]:
    plan = build_library_plan(meta, paths, ctx)
    entries = list(plan.classpath)
    client = paths.client_jar(meta["id"])
    entries.append(client)
    missing = [entry for entry in entries if not entry.is_file()]
    if missing:
        preview = "\n".join(f"  - {item}" for item in missing[:5])
        more = f"\n  ... 还有 {len(missing) - 5} 个" if len(missing) > 5 else ""
        raise LauncherError(
            f"启动所需的 {len(missing)} 个文件不存在：\n{preview}{more}\n"
            f"请先运行 `mcl install {meta['id']}` 补全文件。"
        )
    seen: set[str] = set()
    unique: list[Path] = []
    for entry in entries:
        key = str(entry).lower()
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def build_command(
    meta: dict[str, Any],
    paths: Paths,
    options: LaunchOptions,
    java: Path,
) -> tuple[list[str], dict[str, str]]:
    version_id = meta["id"]
    account = options.account
    if meta.get("id") != options.version_id:
        raise LauncherError("版本元数据与请求的版本不一致")

    natives_dir = paths.natives_dir(version_id)
    natives_dir.mkdir(parents=True, exist_ok=True)
    jar_id = meta.get("jar") or meta["id"]
    client = paths.client_jar(jar_id)
    if not client.is_file():
        raise LauncherError(f"客户端 jar 不存在: {client}")

    width = options.width
    height = options.height
    custom_resolution = width is not None or height is not None
    if custom_resolution:
        width = width or 854
        height = height or 480
    actual_game_dir = Path(options.game_dir) if options.game_dir else paths.game_dir
    features = {
        "is_demo_user": bool(options.demo),
        "has_custom_resolution": custom_resolution,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }
    ctx = build_context(features)

    index_id = (meta.get("assetIndex") or {}).get("id") or meta.get("assets") or "legacy"
    classpath_entries = _classpath(meta, paths, ctx)
    classpath = os.pathsep.join(str(entry) for entry in classpath_entries)
    assets_root = paths.assets
    game_assets = _game_assets_dir(paths, index_id)

    values: dict[str, str] = {
        "auth_player_name": account.name,
        "version_name": version_id,
        "game_directory": str(actual_game_dir),
        "assets_root": str(assets_root),
        "assets_index_name": index_id,
        "auth_uuid": account.uuid_hex,
        "auth_access_token": account.access_token,
        "auth_session": account.access_token,
        "clientid": account.client_id or "mclauncher",
        "auth_xuid": account.xuid,
        "user_type": account.user_type,
        "version_type": meta.get("type", "release"),
        "game_assets": str(game_assets),
        "resolution_width": str(width or 854),
        "resolution_height": str(height or 480),
        "user_properties": "{}",
        "natives_directory": str(natives_dir),
        "launcher_name": "mclauncher",
        "launcher_version": __version__,
        "classpath": classpath,
        "classpath_separator": os.pathsep,
        "library_directory": str(paths.libraries),
    }

    arguments = meta.get("arguments") or {}
    jvm_spec = arguments.get("jvm")
    if jvm_spec is not None:
        jvm_args = _flatten(jvm_spec, ctx, values)
    else:
        jvm_args = [
            "-Djava.library.path=${natives_directory}",
            "-Djna.tmpdir=${natives_directory}",
            "-Dorg.lwjgl.system.SharedLibraryExtractPath=${natives_directory}",
            "-Dio.netty.native.workdir=${natives_directory}",
            "-Dminecraft.launcher.brand=${launcher_name}",
            "-Dminecraft.launcher.version=${launcher_version}",
            "-cp",
            "${classpath}",
        ]
        jvm_args = [_substitute(arg, values) for arg in jvm_args]

    # log4j 配置由启动器附加
    logging = (meta.get("logging") or {}).get("client")
    if logging:
        log_arg = logging.get("argument") or "-Dlog4j.configurationFile=${path}"
        file_id = (logging.get("file") or {}).get("id")
        if file_id:
            log_path = paths.assets / "log_configs" / file_id
            pattern_path = log_path.with_name(log_path.stem + PATTERN_LOG_SUFFIX)
            if pattern_path.is_file():
                log_path = pattern_path
            if log_path.is_file() and not any(arg.startswith("-Dlog4j.configurationFile=") for arg in jvm_args):
                jvm_args.append(
                    log_arg.replace("${path}", str(log_path).replace("\\", "/"))
                )

    if not any(arg == "-cp" or arg == "-classpath" for arg in jvm_args):
        jvm_args.extend(["-cp", classpath])
    if not any(arg.startswith("-Djava.library.path=") for arg in jvm_args):
        jvm_args.append(f"-Djava.library.path={natives_dir}")

    jvm_args.extend(options.jvm_args)

    game_spec = arguments.get("game")
    if game_spec is not None:
        game_args = _flatten(game_spec, ctx, values)
    elif meta.get("minecraftArguments"):
        game_args = [_substitute(part, values) for part in str(meta["minecraftArguments"]).split()]
    else:
        raise LauncherError("版本 JSON 中没有任何游戏启动参数")

    game_args.extend(options.game_args)

    main_class = meta.get("mainClass")
    if not main_class:
        raise LauncherError("版本 JSON 缺少 mainClass")

    memory = options.memory_mb
    memory_args = [f"-Xms{min(1024, memory // 2)}M", f"-Xmx{memory}M"]
    command = [str(java), *memory_args, *jvm_args, main_class, *game_args]
    return command, values


def describe_launch(meta: dict[str, Any], paths: Paths, options: LaunchOptions, java: Path) -> str:
    account_kind = "离线" if options.account.offline else "微软正版"
    return "\n".join(
        [
            f"[*] 启动 Minecraft {meta['id']}",
            f"    账号: {options.account.name}（{account_kind}）",
            f"    Java: {java}",
            f"    内存: {options.memory_mb} MB",
            f"    游戏目录: {paths.game_dir}",
        ]
    )


def _format_command(command: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    import shlex

    return shlex.join(command)


def _ensure_game_language(game_dir: Path, lang_code: str = "zh_cn", stream=sys.stdout) -> None:
    """确保 gameDir 下的 options.txt 使用指定的语言；路径参数化，兼容隔离模式。"""
    options_file = game_dir / "options.txt"
    try:
        if not options_file.is_file():
            options_file.write_text(f"lang:{lang_code}\n", encoding="utf-8")
            return
        lines = options_file.read_text(encoding="utf-8").splitlines()
        has_lang = False
        for i, line in enumerate(lines):
            if line.startswith("lang:"):
                lines[i] = f"lang:{lang_code}"
                has_lang = True
                break
        if not has_lang:
            lines.append(f"lang:{lang_code}")
        options_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[!] 写入游戏语言失败: {exc}", file=stream)


def launch(
    meta: dict[str, Any],
    paths: Paths,
    options: LaunchOptions,
    java: Path,
    stream=sys.stdout,
    on_started: Callable[[subprocess.Popen], None] | None = None,
) -> int:
    if not meta:
        raise LauncherError(f"无法读取版本 {options.version_id} 的元数据，请尝试重新安装该版本。")

    command, _ = build_command(meta, paths, options, java)
    print(describe_launch(meta, paths, options, java), file=stream)

    if options.dry_run:
        print("\n[*] 启动命令（dry-run，不实际执行）:", file=stream)
        print(_format_command(command), file=stream)
        return 0

    # 用实际 gameDir（隔离时为版本目录）
    actual_game_dir = Path(options.game_dir) if options.game_dir else paths.game_dir
    actual_game_dir.mkdir(parents=True, exist_ok=True)

    # 语言设置写到实际目录
    _ensure_game_language(actual_game_dir, "zh_cn", stream=stream)

    print("[*] 正在启动游戏...", file=stream)
    stream.flush()
    try:
        process = subprocess.Popen(command, cwd=str(actual_game_dir))   # ✅ cwd 也改
    except FileNotFoundError as exc:
        raise LauncherError(f"无法执行 Java: {java} ({exc})") from exc
    except OSError as exc:
        raise LauncherError(f"启动失败: {exc}") from exc

    print(f"[+] 游戏进程已启动 (PID {process.pid})", file=stream)
    stream.flush()
    if on_started is not None:
        try:
            on_started(process)
        except Exception:
            pass
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        raise