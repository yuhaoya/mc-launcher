from __future__ import annotations

import re
import shutil
import struct
import sys
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, TextIO

from . import maven
from .errors import LauncherError
from .net import DownloadTask, download_many
from .paths import Paths
from .progress import Progress
from .rules import build_context, current_os, is_allowed
from .util import ensure_dir, file_matches, human_size, link_or_copy, read_json
from .versions import VersionRepository

LIBRARY_BASE = "https://libraries.minecraft.net/"
RESOURCES_BASE = "https://resources.download.minecraft.net/"
PATTERN_LOG_SUFFIX = ".mcl.xml"
LOG_PATTERN = "[%d{HH:mm:ss}] [%t/%level] [%logger]: %msg{nolookups}%n"


@dataclass
class LibraryPlan:
    tasks: list[DownloadTask] = field(default_factory=list)
    classpath: list[Path] = field(default_factory=list)
    native_jars: list[tuple[Path, list[str]]] = field(default_factory=list)


def _artifact_url(entry: dict[str, Any] | None, relative: str) -> str:
    if entry and entry.get("url"):
        return entry["url"]
    return LIBRARY_BASE + relative


def build_library_plan(
        meta: dict[str, Any],
        paths: Paths,
        ctx: dict[str, Any] | None = None,
        mirror_func: Callable[[str], str] | None = None,
) -> LibraryPlan:
    """根据版本 JSON 计算需要下载的库、classpath 顺序以及需要解压的 natives。"""
    ctx = ctx or build_context()
    os_name = current_os()
    mirror_func = mirror_func or (lambda url: url)

    plan = LibraryPlan()
    seen: dict[str, DownloadTask] = {}
    classpath_seen: set[str] = set()

    def add_task(task: DownloadTask) -> None:
        key = str(task.dest).lower()
        if key not in seen:
            # 👇 在加入任务队列时，统一应用镜像转换
            task.url = mirror_func(task.url)
            seen[key] = task
            plan.tasks.append(task)

    def add_classpath(path: Path) -> None:
        key = str(path).lower()
        if key not in classpath_seen:
            classpath_seen.add(key)
            plan.classpath.append(path)

    for lib in meta.get("libraries", []):
        if not is_allowed(lib.get("rules"), ctx):
            continue
        name = lib.get("name") or ""
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact")

        # 1) 普通 jar：进入 classpath
        if artifact:
            relative = artifact.get("path") or maven.relative_path(name)
            dest = paths.library_path(relative)
            add_task(DownloadTask(_artifact_url(artifact, relative), dest, artifact.get("sha1"), artifact.get("size")))
            add_classpath(dest)
        elif not lib.get("natives"):
            # 少数很老的版本没有 downloads 字段，按 Maven 坐标拼 URL
            try:
                relative = maven.relative_path(name)
            except ValueError:
                relative = ""
            if relative:
                dest = paths.library_path(relative)
                add_task(DownloadTask(LIBRARY_BASE + relative, dest))
                add_classpath(dest)

        # 2) 老版本 natives：下载 classifier jar 并解压
        natives = lib.get("natives") or {}
        classifier = natives.get(os_name)
        if not classifier:
            continue
        classifier = classifier.replace("${arch}", "64" if struct.calcsize("P") * 8 == 64 else "32")
        classifiers = downloads.get("classifiers") or {}
        entry = classifiers.get(classifier)
        if entry:
            relative = entry.get("path") or ""
            if not relative:
                parsed = maven.parse(name)
                relative = maven.MavenName(
                    parsed.group, parsed.artifact, parsed.version, classifier=classifier
                ).path
            dest = paths.library_path(relative)
            add_task(DownloadTask(_artifact_url(entry, relative), dest, entry.get("sha1"), entry.get("size")))
        else:
            try:
                parsed = maven.parse(name)
            except ValueError:
                continue
            relative = maven.MavenName(
                parsed.group, parsed.artifact, parsed.version, classifier=classifier
            ).path
            dest = paths.library_path(relative)
            add_task(DownloadTask(LIBRARY_BASE + relative, dest))

        excludes = list((lib.get("extract") or {}).get("exclude") or [])
        plan.native_jars.append((dest, excludes))

    return plan


class Installer:
    def __init__(
        self,
        paths: Paths,
        workers: int = 8,
        stream: TextIO | None = None,
        enabled: bool = True,
        callback: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
        log_callback: Callable[[str], None] | None = None,
        mirror_func: Callable[[str], str] | None = None,
    ):
        self.paths = paths
        self.workers = max(1, workers)
        self.stream = stream or sys.stdout
        self.enabled = enabled
        self.callback = callback
        self.cancel_event = cancel_event
        self.log_callback = log_callback
        self.repo = VersionRepository(paths, self.stream)
        self.mirror_func = mirror_func or (lambda url: url)

    # ------------------------------------------------------------------
    def log(self, message: str = "") -> None:
        print(message, file=self.stream)
        if self.log_callback is not None:
            try:
                self.log_callback(message)
            except Exception:
                pass

    def _download(self, tasks: list[DownloadTask], label: str) -> None:
        if not tasks:
            return
        result = download_many(
            tasks,
            workers=self.workers,
            label=label,
            stream=self.stream,
            enabled=self.enabled,
            callback=self.callback,
            cancel_event=self.cancel_event,
        )
        if result["downloaded"] == 0 and result["total"]:
            self.log(f"    已完整，跳过 {result['total']} 个文件")

    # ------------------------------------------------------------------
    def install(
        self,
        version_id: str,
        skip_assets: bool = False,
        force: bool = False,
        with_java: bool = False,
    ) -> dict[str, Any]:
        ensure_dir(self.paths.game_dir)
        meta = self.repo.meta(version_id, force=force)
        version_type = meta.get("type", "release")
        self.log(f"[*] 安装 Minecraft {version_id} ({version_type})")
        self.log(f"    游戏目录: {self.paths.game_dir}")

        self._install_client(meta)
        self._install_libraries(meta)
        if skip_assets:
            self.log("[*] 按参数跳过资源文件")
        else:
            self._install_assets(meta)
        self._install_logging(meta)

        if with_java:
            from .java import ensure_java

            ensure_java(
                meta,
                self.paths,
                allow_install=True,
                stream=self.stream,
                callback=self.callback,
                cancel_event=self.cancel_event,
            )

        client = self.paths.client_jar(version_id)
        if not client.is_file() or client.stat().st_size == 0:
            raise LauncherError("客户端 jar 缺失，安装似乎没有完成")
        self.log(f"[+] Minecraft {version_id} 安装完成")
        return meta

    # ------------------------------------------------------------------
    def _install_client(self, meta: dict[str, Any]) -> None:
        version_id = meta["id"]
        client = (meta.get("downloads") or {}).get("client")
        if not client or not client.get("url"):
            raise LauncherError(f"版本 {version_id} 没有客户端下载信息")
        dest = self.paths.client_jar(version_id)
        if file_matches(dest, client.get("sha1"), client.get("size")):
            self.log("[*] 客户端 jar 已存在")
            return
        self._download(
            [DownloadTask(self.mirror_func(client["url"]), dest, client.get("sha1"), client.get("size"))],
            "下载客户端 jar",
        )

    def _install_libraries(self, meta: dict[str, Any]) -> None:
        plan = build_library_plan(meta, self.paths, mirror_func=self.mirror_func)
        self._download(plan.tasks, f"下载依赖库 ({len(plan.tasks)})")
        self._extract_natives(meta["id"], plan.native_jars)

    def _extract_natives(self, version_id: str, native_jars: list[tuple[Path, list[str]]]) -> None:
        natives_dir = self.paths.natives_dir(version_id)
        if natives_dir.exists():
            shutil.rmtree(natives_dir)
        ensure_dir(natives_dir)
        if not native_jars:
            return
        self.log(f"[*] 解压 natives ({len(native_jars)} 个包)")
        for jar, excludes in native_jars:
            if not jar.is_file():
                raise LauncherError(f"natives 文件缺失: {jar}")
            with zipfile.ZipFile(jar) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename.replace("\\", "/")
                    if name.startswith("META-INF/"):
                        continue
                    if any(name.startswith(prefix) for prefix in excludes):
                        continue
                    parts = PurePosixPath(name).parts
                    if not parts or ".." in parts or name.startswith("/"):
                        continue
                    target = natives_dir.joinpath(*parts)
                    ensure_dir(target.parent)
                    with archive.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

    # ------------------------------------------------------------------
    def _install_assets(self, meta: dict[str, Any]) -> str | None:
        index_meta = meta.get("assetIndex")
        if not index_meta:
            self.log("[!] 该版本没有资源索引，跳过资源文件")
            return None

        index_id = index_meta["id"]
        dest = self.paths.assets_indexes / f"{index_id}.json"
        if not file_matches(dest, index_meta.get("sha1"), index_meta.get("size")):
            self._download(
                [DownloadTask(index_meta["url"], dest, index_meta.get("sha1"), index_meta.get("size"))],
                f"资源索引 {index_id}",
            )
        index = read_json(dest)
        if not isinstance(index, dict) or "objects" not in index:
            raise LauncherError(f"资源索引 {index_id} 无效")

        objects = index.get("objects") or {}
        tasks = []
        seen: set[str] = set()
        for name, obj in objects.items():
            digest = obj.get("hash", "")
            if not digest or digest in seen:
                continue
            seen.add(digest)
            tasks.append(
                DownloadTask(
                    self.mirror_func(f"{RESOURCES_BASE}{digest[:2]}/{digest}"),
                    self.paths.assets_objects / digest[:2] / digest,
                    digest,
                    obj.get("size"),
                )
            )
        self.log(f"[*] 资源文件 {len(tasks)} 个，共 {human_size(sum(t.size or 0 for t in tasks))}")
        self._download(tasks, f"下载资源文件 ({len(tasks)})")
        self._materialize_assets(index_id, index)
        return index_id

    def _materialize_assets(self, index_id: str, index: dict[str, Any]) -> None:
        objects = index.get("objects") or {}
        if index.get("map_to_resources"):
            target = self.paths.game_dir / "resources"
        elif index.get("virtual"):
            target = self.paths.assets_virtual / index_id
        else:
            return
        self.log(f"[*] 整理旧版资源到 {target}")
        ensure_dir(target)
        total_bytes = sum((obj.get("size") or 0) for obj in objects.values())
        progress = Progress(
            f"整理资源 ({len(objects)})",
            total_bytes,
            stream=self.stream,
            enabled=self.enabled,
            callback=self.callback,
            cancel_event=self.cancel_event,
        )
        for name, obj in objects.items():
            digest = obj.get("hash")
            if not digest:
                continue
            parts = PurePosixPath(name).parts
            if not parts or ".." in parts or name.startswith("/"):
                continue
            src = self.paths.assets_objects / digest[:2] / digest
            dst = target.joinpath(*parts)
            if not file_matches(dst, None, obj.get("size")):
                link_or_copy(src, dst)
            progress.advance(obj.get("size") or 0)
        progress.finish()

    # ------------------------------------------------------------------
    def _install_logging(self, meta: dict[str, Any]) -> None:
        logging = (meta.get("logging") or {}).get("client")
        if not logging:
            return
        file_info = logging.get("file") or {}
        url = file_info.get("url")
        file_id = file_info.get("id")
        if not url or not file_id:
            return
        dest = self.paths.assets / "log_configs" / file_id
        if not file_matches(dest, file_info.get("sha1"), file_info.get("size")):
            self._download(
                [DownloadTask(url, dest, file_info.get("sha1"), file_info.get("size"))],
                "下载日志配置",
            )
        self._ensure_pattern_log(dest)

    @staticmethod
    def _ensure_pattern_log(source: Path) -> None:
        """官方配置用 LegacyXMLLayout 输出 XML，命令行里可读性很差。

        复制一份把 XML 布局换成普通 PatternLayout 的配置供启动器使用。
        """
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return
        if "<LegacyXMLLayout" not in text:
            return
        replacement = f'<PatternLayout pattern="{LOG_PATTERN}" />'
        updated = re.sub(r"<LegacyXMLLayout\s*/>", replacement, text)
        target = source.with_name(source.stem + PATTERN_LOG_SUFFIX)
        try:
            if not target.is_file() or target.read_text(encoding="utf-8") != updated:
                target.write_text(updated, encoding="utf-8")
        except OSError:
            pass


def is_installed(paths: Paths, version_id: str) -> bool:
    json_file = paths.version_json(version_id)
    jar = paths.client_jar(version_id)
    return json_file.is_file() and jar.is_file() and jar.stat().st_size > 0
