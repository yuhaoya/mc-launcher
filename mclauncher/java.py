from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, TextIO

from .errors import DownloadError, LauncherError
from .net import DownloadTask, download_many, get_bytes
from .paths import Paths
from .util import ensure_dir, write_json_atomic

JAVA_RUNTIME_URL = (
    "https://launchermeta.mojang.com/v1/products/java-runtime/"
    "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
)
JAVA_RUNTIME_TTL = 24 * 3600

_VERSION_CACHE: dict[str, int | None] = {}


def _creation_flags() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def detect_java_major(java: Path) -> int | None:
    key = str(java).lower()
    if key in _VERSION_CACHE:
        return _VERSION_CACHE[key]
    major: int | None = None
    if java.is_file():
        try:
            proc = subprocess.run(
                [str(java), "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                creationflags=_creation_flags(),
            )
            text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
            match = re.search(r'version\s+"([^"]+)"', text)
            if match:
                version = match.group(1)
                if version.startswith("1."):
                    major = int(version.split(".")[1])
                else:
                    leading = re.match(r"(\d+)", version)
                    if leading:
                        major = int(leading.group(1))
        except (OSError, subprocess.SubprocessError):
            major = None
    _VERSION_CACHE[key] = major
    return major


def _java_exe(home: Path) -> Path:
    return home / "bin" / ("java.exe" if sys.platform == "win32" else "java")


def _registry_homes() -> Iterable[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    homes: list[Path] = []
    subkeys = (
        r"SOFTWARE\JavaSoft\Java Runtime Environment",
        r"SOFTWARE\JavaSoft\Java Development Kit",
        r"SOFTWARE\JavaSoft\JDK",
    )
    for subkey in subkeys:
        for view in (
            getattr(winreg, "KEY_WOW64_64KEY", 0),
            getattr(winreg, "KEY_WOW64_32KEY", 0),
        ):
            try:
                root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            try:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        child = winreg.OpenKey(root, name)
                        home, _ = winreg.QueryValueEx(child, "JavaHome")
                        winreg.CloseKey(child)
                        homes.append(Path(home))
                    except OSError:
                        continue
            finally:
                winreg.CloseKey(root)
    return homes


def _common_homes() -> Iterable[Path]:
    if sys.platform == "win32":
        patterns = [
            r"C:\Program Files\Java\*",
            r"C:\Program Files\Eclipse Adoptium\*",
            r"C:\Program Files\Microsoft\jdk-*",
            r"C:\Program Files\BellSoft\*",
            r"C:\Program Files\Zulu\*",
            r"C:\Program Files\Amazon Corretto\*",
            r"C:\Program Files\Semeru\*",
            r"C:\Program Files (x86)\Java\*",
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Eclipse Adoptium" / "*"),
        ]
        for pattern in patterns:
            for path in glob.glob(pattern):
                yield Path(path)
    else:
        for pattern in ("/usr/lib/jvm/*", "/Library/Java/JavaVirtualMachines/*/Contents/Home"):
            for path in glob.glob(pattern):
                yield Path(path)


def candidate_javas(paths: Paths, configured: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if not path:
            return
        path = Path(path).expanduser()
        if path.is_dir():
            path = _java_exe(path)
        if path.is_file():
            candidates.append(path)

    if configured:
        add(Path(configured))

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        add(Path(java_home))

    for name in ("java",):
        found = shutil.which(name)
        if found:
            add(Path(found))

    if paths.runtime.is_dir():
        for found in paths.runtime.rglob("java.exe" if sys.platform == "win32" else "java"):
            if found.is_file():
                add(found)

    for home in _registry_homes():
        add(home)
    for home in _common_homes():
        add(home)

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def list_javas(paths: Paths, configured: str | Path | None = None) -> list[tuple[Path, int | None]]:
    result = []
    for path in candidate_javas(paths, configured):
        result.append((path, detect_java_major(path)))
    return sorted(result, key=lambda item: (item[1] is None, item[1] or 0, str(item[0])))


def find_java(
    paths: Paths,
    required_major: int,
    configured: str | Path | None = None,
    allow_higher: bool = True,
) -> tuple[Path, int] | None:
    exact: tuple[Path, int] | None = None
    higher: list[tuple[int, Path]] = []
    for path in candidate_javas(paths, configured):
        major = detect_java_major(path)
        if major is None:
            continue
        if major == required_major:
            exact = (path, major)
            break
        if major > required_major:
            higher.append((major, path))
    if exact:
        return exact
    # Java 有较好的向后兼容性：17 可以跑大多数要求 17 的版本，21 也可以。
    # 但对 Java 8/16 时代的老版本不做这种猜测。
    if allow_higher and required_major >= 17 and higher:
        higher.sort(key=lambda item: item[0])
        return higher[0][1], higher[0][0]
    return None


def java_platform_tag() -> str:
    is_64 = struct.calcsize("P") * 8 == 64
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        if machine in ("arm64", "aarch64"):
            return "windows-arm64"
        return "windows-x64" if is_64 else "windows-x86"
    if system == "Darwin":
        return "mac-os-arm64" if machine in ("arm64", "aarch64") else "mac-os"
    return "linux" if is_64 else "linux-i386"


def _java_binary(root: Path) -> Path:
    name = "java.exe" if sys.platform == "win32" else "java"
    direct = root / "bin" / name
    if direct.is_file():
        return direct
    found = list(root.rglob(name))
    if found:
        return found[0]
    return direct


def _major_from_runtime_version(version_name: str, component: str) -> int | None:
    text = (version_name or "").strip()
    if text.startswith("1."):
        parts = text.split(".")
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    match = re.match(r"(\d+)", text)
    if match:
        value = int(match.group(1))
        # 8u51 形式的版本号
        if "u" in text[: len(match.group(0)) + 1] or value >= 8:
            return value
    mapping = {
        "jre-legacy": 8,
        "java-runtime-alpha": 16,
        "java-runtime-beta": 17,
        "java-runtime-gamma": 17,
        "java-runtime-delta": 21,
        "java-runtime-epsilon": 25,
    }
    return mapping.get(component)


def _runtime_manifest(force: bool = False) -> dict[str, Any]:
    # 运行时清单很小，直接内存缓存 24 小时。
    global _RUNTIME_CACHE, _RUNTIME_CACHE_TIME
    if not force and _RUNTIME_CACHE and time.time() - _RUNTIME_CACHE_TIME < JAVA_RUNTIME_TTL:
        return _RUNTIME_CACHE
    _RUNTIME_CACHE = json.loads(get_bytes(JAVA_RUNTIME_URL, timeout=60).decode("utf-8-sig"))
    _RUNTIME_CACHE_TIME = time.time()
    return _RUNTIME_CACHE


_RUNTIME_CACHE: dict[str, Any] = {}
_RUNTIME_CACHE_TIME = 0.0


def _pick_runtime(
    all_json: dict[str, Any],
    platform_tag: str,
    component: str | None,
    major: int | None,
) -> tuple[str, dict[str, Any], int | None]:
    entries = all_json.get(platform_tag) or {}
    candidates: list[tuple[str, dict[str, Any], int | None]] = []
    for comp, comp_entries in entries.items():
        if comp == "minecraft-java-exe":
            continue
        for entry in comp_entries:
            version_name = ((entry.get("version") or {}).get("name")) or ""
            entry_major = _major_from_runtime_version(version_name, comp)
            candidates.append((comp, entry, entry_major))

    if component:
        filtered = [item for item in candidates if item[0] == component]
        if filtered:
            if major is not None:
                same = [item for item in filtered if item[2] == major]
                if same:
                    filtered = same
            return max(filtered, key=lambda item: (item[1].get("version") or {}).get("released", ""))

    filtered = [item for item in candidates if major is not None and item[2] == major]
    if not filtered:
        available = sorted({item[0] for item in candidates})
        raise LauncherError(
            f"Mojang 没有提供适用于 {platform_tag} 的 Java {major} 运行时。"
            f"可用组件: {', '.join(available)}"
        )
    # 优先稳定的正式组件；同 major 下取发布日期最新的。
    stable = [item for item in filtered if "snapshot" not in item[0]]
    if stable:
        filtered = stable
    return max(filtered, key=lambda item: (item[1].get("version") or {}).get("released", ""))


def install_runtime(
    paths: Paths,
    major: int | None = None,
    component: str | None = None,
    workers: int = 8,
    stream: TextIO | None = None,
    enabled: bool = True,
    force: bool = False,
    callback: Callable[[dict], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    stream = stream or sys.stdout
    platform_tag = java_platform_tag()
    all_json = _runtime_manifest(force=force)
    comp, entry, entry_major = _pick_runtime(all_json, platform_tag, component, major)
    required_major = major if major is not None else entry_major

    root = paths.runtime / comp / platform_tag / comp
    java_exe = _java_binary(root)
    if java_exe.is_file() and detect_java_major(java_exe) == required_major and not force:
        return java_exe

    print(f"[*] 下载 Mojang Java 运行时 {comp} ({platform_tag})", file=stream)
    manifest_info = entry.get("manifest") or {}
    if not manifest_info.get("url"):
        raise LauncherError(f"运行时 {comp} 缺少清单地址")

    raw = get_bytes(manifest_info["url"], timeout=60)
    if manifest_info.get("sha1") and hashlib.sha1(raw).hexdigest() != manifest_info["sha1"].lower():
        raise DownloadError("Java 运行时清单 SHA1 校验失败")
    manifest = json.loads(raw.decode("utf-8-sig"))
    files = manifest.get("files") or {}

    tasks: list[DownloadTask] = []
    total = 0
    for target, info in files.items():
        path_parts = PurePosixPath(target).parts
        if not path_parts or ".." in path_parts:
            continue
        if info.get("type") == "directory":
            ensure_dir(root.joinpath(*path_parts))
            continue
        if info.get("type") != "file":
            continue
        download = ((info.get("downloads") or {}).get("raw")) or {}
        if not download.get("url"):
            continue
        dest = root.joinpath(*path_parts)
        tasks.append(DownloadTask(download["url"], dest, download.get("sha1"), download.get("size")))
        total += download.get("size") or 0

    print(f"    共 {len(tasks)} 个文件，{total / 1024 / 1024:.0f} MB", file=stream)
    download_many(
        tasks,
        workers=workers,
        label=f"下载 Java {comp}",
        stream=stream,
        enabled=enabled,
        callback=callback,
        cancel_event=cancel_event,
    )

    java_exe = _java_binary(root)
    if not java_exe.is_file():
        raise LauncherError(f"Java 运行时安装失败：找不到 {java_exe}")
    detected = detect_java_major(java_exe)
    if required_major is not None and detected != required_major:
        raise LauncherError(f"Java 运行时版本异常：期望 {required_major}，实际 {detected}")
    write_json_atomic(
        paths.runtime / comp / platform_tag / ".mclauncher.json",
        {
            "component": comp,
            "platform": platform_tag,
            "version": (entry.get("version") or {}).get("name"),
            "manifest": manifest_info.get("url"),
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return java_exe


def ensure_java(
    meta: dict[str, Any],
    paths: Paths,
    configured: str | Path | None = None,
    allow_install: bool = True,
    stream: TextIO | None = None,
    callback: Callable[[dict], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    stream = stream or sys.stdout
    java_info = meta.get("javaVersion") or {}
    required = int(java_info.get("majorVersion") or 8)
    found = find_java(paths, required, configured)
    if found:
        path, actual = found
        if actual != required:
            print(f"[!] 未找到 Java {required}，改用 Java {actual}（{path}）", file=stream)
        return path

    if not allow_install:
        raise LauncherError(
            f"需要 Java {required}，但没有找到。安装一个 Java {required} 后重试，"
            f"或去掉 --no-auto-java 让启动器自动下载。"
        )

    print(f"[*] 未找到 Java {required}，准备下载 Mojang 官方运行时（约 90–150MB）", file=stream)
    component = java_info.get("component")
    path = install_runtime(
        paths,
        major=required,
        component=component,
        stream=stream,
        callback=callback,
        cancel_event=cancel_event,
    )
    print(f"[+] Java 运行时已就绪: {path}", file=stream)
    return path
