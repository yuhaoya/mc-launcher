from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any, Callable
import copy,json
import urllib.request

from .auth import (
    Account,
    cached_profile,
    get_account,
    login as auth_login,
    logout as auth_logout,
    offline_account,
)
from .config import Config
from .errors import AuthError, LauncherError
from .installer import Installer, is_installed
from .java import ensure_java, list_javas
from .launcher import LaunchOptions, launch as launch_game
from .paths import Paths, default_game_dir
from .util import human_size, parse_memory_mb
from .versions import VersionRepository

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[dict], None]
StartedCallback = Callable[[int], None]
CodeCallback = Callable[[dict], None]
StatusCallback = Callable[[str], None]


class LauncherService:
    """GUI / TUI 共用的业务层。

    所有可能阻塞的方法（install / launch / login / javas）都由调用方放到
    工作线程里执行；这里只负责配置、路径和启动器核心 API 的组合。
    """

    def __init__(self, game_dir: str | Path | None = None, config_dir: str | Path | None = None):
        self.config = Config(Path(config_dir) if config_dir else None)
        self.paths = self._build_paths(game_dir)
        self.repo = VersionRepository(self.paths)

    def _build_paths(self, game_dir: str | Path | None = None) -> Paths:
        raw = game_dir or self.config.get("game_dir") or default_game_dir()
        game = Path(raw).expanduser().resolve()
        return Paths(game, self.config.dir)

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        return {
            "game_dir": str(self.paths.game_dir),
            "config_dir": str(self.config.dir),
            "memory_mb": int(self.config.get("memory_mb") or 4096),
            "java_path": self.config.get("java_path") or "",
            "offline_name": self.config.get("offline_name") or "Player",
            "theme": self.config.get("theme") or "auto",
            "accent": self.config.get("accent") or "blue",
            "isolate_versions": bool(self.config.get("isolate_versions") or False),  # ← 新增
        }

    def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        game_dir = values.get("game_dir")
        if game_dir:
            new_paths = self._build_paths(str(game_dir))
            if new_paths.game_dir != self.paths.game_dir:
                self.config.set("game_dir", str(new_paths.game_dir))
                self.paths = new_paths
                self.repo = VersionRepository(self.paths)
        if "memory_mb" in values:
            self.config.set("memory_mb", parse_memory_mb(values["memory_mb"]))
        if "java_path" in values:
            java_path = str(values["java_path"] or "").strip()
            self.config.set("java_path", java_path or None)
        if "offline_name" in values:
            name = str(values["offline_name"] or "").strip() or "Player"
            offline_account(name)  # 校验，失败直接抛给 UI
            self.config.set("offline_name", name)
        if "theme" in values:
            self.config.set("theme", values["theme"])
        if "accent" in values:
            self.config.set("accent", values["accent"])
        if "isolate_versions" in values:
            self.config.set("isolate_versions", bool(values["isolate_versions"]))
        self.config.save()
        return self.settings()

    # ------------------------------------------------------------------
    # account
    # ------------------------------------------------------------------
    def account(self) -> dict[str, Any] | None:
        active = self.config.get("active_account") or {}
        kind = active.get("kind")
        name = active.get("name")

        if kind == "microsoft":
            profile = cached_profile(self.config)
            if profile:
                return {
                    "name": profile.get("name") or "Player",
                    "uuid": profile.get("uuid") or "",
                    "kind": "microsoft",
                    "offline": False,
                    "expires_at": profile.get("expires_at") or 0,
                }
            # 微软缓存失效，自动降级到离线
            kind = "offline"
            name = name or self.config.get("offline_name") or "Player"

        if kind == "offline" and name:
            try:
                offline = offline_account(str(name))
                return {
                    "name": offline.name,
                    "uuid": offline.uuid,
                    "kind": "offline",
                    "offline": True,
                    "expires_at": 0,
                }
            except AuthError:
                pass

        # 兼容旧数据：没写过 active_account 的情况
        profile = cached_profile(self.config)
        if profile:
            return {
                "name": profile.get("name") or "Player",
                "uuid": profile.get("uuid") or "",
                "kind": "microsoft",
                "offline": False,
                "expires_at": profile.get("expires_at") or 0,
            }
        name = str(self.config.get("offline_name") or "Player")
        try:
            offline = offline_account(name)
        except AuthError:
            return None
        return {
            "name": offline.name,
            "uuid": offline.uuid,
            "kind": "offline",
            "offline": True,
            "expires_at": 0,
        }

    def login(
        self,
        client_id: str | None = None,
        open_browser: bool = True,
        on_code: CodeCallback | None = None,
        on_status: StatusCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        account = auth_login(
            self.config,
            client_id=client_id,
            stream=io.StringIO(),
            open_browser=open_browser,
            on_code=on_code,
            on_status=on_status,
            cancel_event=cancel_event,
        )
        self.config.set("active_account", {"kind": "microsoft"})
        self.config.save()
        return {
            "name": account.name,
            "uuid": account.uuid,
            "kind": "microsoft",
            "offline": False,
            "expires_at": account.expires_at,
        }

    def logout(self) -> None:
        auth_logout(self.config)
        fallback = str(self.config.get("offline_name") or "Player")
        self.config.set("active_account", {"kind": "offline", "name": fallback})
        self.config.save()

    # ------------------------------------------------------------------
    # 账号管理：支持保存多个离线账号并随时切换
    # ------------------------------------------------------------------
    def _offline_names(self) -> list[str]:
        names = list(self.config.get("offline_names") or [])
        current = str(self.config.get("offline_name") or "Player")
        if current and current not in names:
            names.append(current)
        return names

    def list_accounts(self) -> list[dict[str, Any]]:
        active = self.config.get("active_account") or {}
        active_kind = active.get("kind")
        active_name = active.get("name")

        result: list[dict[str, Any]] = []

        # 微软正版（有缓存时显示，可切回）
        profile = cached_profile(self.config)
        if profile:
            result.append({
                "name": profile.get("name") or "Player",
                "kind": "微软正版",
                "uuid": profile.get("uuid") or "",
                "active": active_kind == "microsoft",
            })

        # 离线账号
        seen: set[str] = set()
        for name in self._offline_names():
            if name in seen:
                continue
            seen.add(name)
            try:
                offline = offline_account(name)
            except AuthError:
                continue
            result.append({
                "name": offline.name,
                "kind": "离线账号",
                "uuid": offline.uuid,
                "active": active_kind == "offline" and active_name == offline.name,
            })
        return result

    def add_offline_account(self, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            raise AuthError("离线用户名不能为空")
        names = self._offline_names()
        if name not in names:
            names.append(name)
        self.config.set("offline_names", names)
        self.config.save()

    def remove_offline_account(self, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            raise AuthError("离线用户名不能为空")
        names = [n for n in self._offline_names() if n != name]
        if not names:
            raise AuthError("至少保留一个离线账号")
        self.config.set("offline_names", names)
        if str(self.config.get("offline_name") or "Player") == name:
            self.config.set("offline_name", names[0])
        self.config.save()

    def switch_account(self, name: str) -> None:
        """切换当前激活账号，支持离线账号与已登录的微软账号之间切换。"""
        name = str(name or "").strip()
        if not name:
            raise AuthError("账号名不能为空")

        # 优先匹配离线账号（离线名字任意合法即可）
        if name in self._offline_names():
            offline_account(name)  # 校验合法性
            self.config.set("offline_name", name)
            self.config.set("active_account", {"kind": "offline", "name": name})
            self.config.save()
            return

        # 匹配微软账号
        profile = cached_profile(self.config)
        if profile and (profile.get("name") or "") == name:
            self.config.set("active_account", {"kind": "microsoft"})
            self.config.save()
            return

        raise AuthError(f"账号 {name!r} 不存在，请先添加")

    # ------------------------------------------------------------------
    # versions
    # ------------------------------------------------------------------
    def versions(self, force: bool = False) -> dict[str, Any]:
        manifest = self.repo.manifest(force=force)

        # 获取已经成功安装的版本（包含 Fabric）
        local_installed = self.installed_versions()
        installed_ids = {v["id"] for v in local_installed}

        # 生成 Mojang 官方原版列表
        versions = [
            {
                "id": item.get("id", ""),
                "type": item.get("type", "release"),
                "release_time": item.get("releaseTime", ""),
                "installed": item.get("id") in installed_ids,
            }
            for item in manifest.get("versions", [])
        ]

        # 👇 核心修复：把本地安装的 Fabric 等合并进列表
        existing_ids = {v["id"] for v in versions}
        for local in local_installed:
            if local["id"] not in existing_ids:
                versions.insert(0, {
                    "id": local["id"],
                    "type": local.get("type", "fabric"),
                    "release_time": local.get("release_time", ""),
                    "installed": True,
                })

        return {
            "latest": manifest.get("latest", {}),
            "versions": versions,
            "fetched_at": time.time(),
        }

    def installed_versions(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for version_id in self.repo.installed_versions():
            meta_path = self.paths.version_json(version_id)
            if not meta_path.is_file():
                continue

            meta = {}
            try:
                import json
                meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            except Exception:
                pass

            # 👇 核心修复：如果是继承版本（Fabric/Forge），检查父版本；否则检查自身
            if meta.get("inheritsFrom"):
                parent_id = meta["inheritsFrom"]
                # 只检查父版本的 json 和 jar 是否存在
                if not is_installed(self.paths, parent_id):
                    continue
            else:
                # 原版严格检查自身
                if not is_installed(self.paths, version_id):
                    continue

            # 获取文件大小（Fabric 本身没有 jar，大小可能为 0，不影响显示）
            jar = self.paths.client_jar(version_id)
            try:
                size = jar.stat().st_size
            except OSError:
                size = 0

            # 识别类型，方便界面显示
            v_type = meta.get("type", "release")
            if "fabric" in version_id.lower():
                v_type = "fabric"
            elif "forge" in version_id.lower():
                v_type = "forge"

            result.append(
                {
                    "id": version_id,
                    "type": v_type,
                    "release_time": meta.get("releaseTime", ""),
                    "path": str(self.paths.version_dir(version_id)),
                    "size": size,
                    "size_text": human_size(size) if size > 0 else "无独立客户端",
                }
            )

        # 👇 按文件夹修改时间倒序排列，保证刚安装的 Fabric 排在最前面
        result.sort(key=lambda item: self.paths.version_dir(item["id"]).stat().st_mtime, reverse=True)
        return result

    # ------------------------------------------------------------------
    # install / launch
    # ------------------------------------------------------------------
    def install(
        self,
        version_id: str,
        skip_assets: bool = False,
        with_java: bool = True,
        callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        cancel_event: threading.Event | None = None,
        workers: int = 16,
    ) -> dict[str, Any]:
        installer = Installer(
            self.paths,
            workers=workers,
            stream=io.StringIO(),
            enabled=False,
            callback=callback,
            cancel_event=cancel_event,
            log_callback=log_callback,
        )
        meta = installer.install(
            version_id,
            skip_assets=skip_assets,
            with_java=with_java,
        )
        return {"id": meta.get("id", version_id), "type": meta.get("type", "release")}

    def resolve_account(self, offline_name: str | None = None) -> Account:
        name = (offline_name or "").strip()
        if name:
            return offline_account(name)

        active = self.config.get("active_account") or {}
        kind = active.get("kind")
        active_name = active.get("name")

        if kind == "microsoft":
            try:
                return get_account(self.config)
            except AuthError as exc:
                fallback = str(active_name or self.config.get("offline_name") or "Player")
                print(f"[!] 微软账号验证失败，自动降级到离线: {fallback} ({exc})")
                return offline_account(fallback)

        if kind == "offline" and active_name:
            return offline_account(str(active_name))

        # 兼容旧数据
        if self.config.get("msa"):
            try:
                return get_account(self.config)
            except AuthError as exc:
                fallback = str(self.config.get("offline_name") or "Player")
                print(f"[!] 微软账号验证失败，自动降级到离线: {fallback} ({exc})")
                return offline_account(fallback)
        return offline_account(str(self.config.get("offline_name") or "Player"))

    def launch(
        self,
        version_id: str,
        offline_name: str | None = None,
        memory_mb: int | None = None,
        java_path: str | Path | None = None,
        demo: bool = False,
        width: int | None = None,
        height: int | None = None,
        dry_run: bool = False,
        callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        on_started: StartedCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if not is_installed(self.paths, version_id):
            raise LauncherError(f"{version_id} 还没有安装完整，请先安装。")
        meta = self.load_merged_version_json(version_id)
        account = self.resolve_account(offline_name)
        stream = io.StringIO()
        java = Path(java_path) if java_path else None
        if java is None or not java.is_file():
            java = ensure_java(
                meta,
                self.paths,
                configured=java_path or self.config.get("java_path"),
                allow_install=True,
                stream=stream,
                callback=callback,
                cancel_event=cancel_event,
            )
        memory = parse_memory_mb(memory_mb if memory_mb is not None else self.config.get("memory_mb") or 4096)
        isolate = bool(self.config.get("isolate_versions") or False)
        game_dir = self.paths.instance_game_dir(version_id, isolate)
        if isolate:
            # 确保版本隔离目录存在，mods/saves 等会在其中生成
            game_dir.mkdir(parents=True, exist_ok=True)
        options = LaunchOptions(
            version_id=version_id,
            account=account,
            memory_mb=memory,
            width=width,
            height=height,
            demo=demo,
            dry_run=dry_run,
            game_dir=str(game_dir),
        )
        if dry_run:
            from .launcher import build_command, describe_launch

            command, _ = build_command(meta, self.paths, options, java)
            return {
                "dry_run": True,
                "command": command,
                "description": describe_launch(meta, self.paths, options, java),
                "pid": 0,
                "exit_code": 0,
            }
        pid_box: list[int] = []

        def _started(process) -> None:
            pid_box.append(process.pid)
            if on_started is not None:
                try:
                    on_started(process.pid)
                except Exception:
                    pass

        code = launch_game(
            meta,
            self.paths,
            options,
            java,
            stream=stream,
            on_started=_started,
        )
        return {
            "dry_run": False,
            "pid": pid_box[0] if pid_box else 0,
            "exit_code": code,
            "account": {"name": account.name, "uuid": account.uuid, "offline": account.offline},
        }

    # ------------------------------------------------------------------
    # java / misc
    # ------------------------------------------------------------------
    def javas(self) -> list[dict[str, Any]]:
        result = []
        for path, major in list_javas(self.paths, self.config.get("java_path")):
            result.append(
                {
                    "path": str(path),
                    "major": major,
                    "version": f"Java {major}" if major else "未知版本",
                }
            )
        return result

    def detect_java(self, path: str) -> int | None:
        from .java import detect_java_major

        return detect_java_major(Path(path))

    def load_merged_version_json(self, version_id: str) -> dict[str, Any]:
        """递归合并 inheritsFrom，支持 Forge / Fabric 等多层继承"""
        meta_path = self.paths.version_json(version_id)
        if not meta_path.is_file():
            raise LauncherError(f"找不到版本文件: {meta_path}")

        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        parent_id = meta.get("inheritsFrom")
        if not parent_id:
            return meta

        # 递归加载父版本
        parent = self.load_merged_version_json(parent_id)

        # 开始合并
        merged = copy.deepcopy(parent)
        for key, value in meta.items():
            if key == "libraries":
                # 库合并：子类库追加到后面，启动器在去重时会优先使用子类
                merged["libraries"] = merged.get("libraries", []) + (value or [])
            elif key == "arguments":
                # 参数合并：JVM 和 Game 参数分别拼接
                merged["arguments"] = merged.get("arguments", {})
                for arg_key, arg_list in value.items():
                    if isinstance(arg_list, list):
                        merged["arguments"].setdefault(arg_key, []).extend(arg_list)
            elif key == "minecraftArguments":
                # 老版本 Forge 的合并方式
                old_args = merged.get("minecraftArguments", "")
                new_args = value or ""
                merged["minecraftArguments"] = f"{old_args} {new_args}".strip()
            else:
                # 其他字段（mainClass, id 等）直接覆盖
                merged[key] = value

        # 继承后的版本，必须使用父版本的客户端 jar（即原版 jar）
        # 如果子类 JSON 没有明确指定 jar 字段，就使用父类的 id
        if "jar" not in meta:
            merged["jar"] = parent.get("id", parent_id)

        return merged

    def install_fabric(
            self,
            mc_version: str,
            callback: ProgressCallback | None = None,
            log_callback: LogCallback | None = None,
            cancel_event: threading.Event | None = None
    ) -> dict[str, Any]:
        import urllib.request
        import shutil

        def check_cancel():
            if cancel_event and cancel_event.is_set():
                raise LauncherError("安装已取消")

        def log(msg):
            if log_callback:
                log_callback(f"[*] {msg}")

        check_cancel()

        # 1. 确保原版已安装
        if not is_installed(self.paths, mc_version):
            log(f"检测到原版 {mc_version} 未安装，准备先安装原版...")
            try:
                self.install(
                    mc_version,
                    with_java=True,
                    callback=callback,
                    log_callback=log_callback,
                    cancel_event=cancel_event
                )
            except Exception as e:
                check_cancel()
                raise LauncherError(f"前置原版安装失败: {e}")

        # 2. 获取 Fabric 数据
        log(f"正在获取 Fabric {mc_version} 的版本信息...")
        try:
            url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
            req = urllib.request.urlopen(url)
            data = json.loads(req.read().decode())
            loader_version = data[0]["loader"]["version"]

            profile_url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/profile/json"
            req = urllib.request.urlopen(profile_url)
            fabric_meta = json.loads(req.read().decode())
        except Exception as e:
            check_cancel()
            raise LauncherError(f"获取 Fabric 信息失败: {e}")

        check_cancel()

        # 3. 合并原版和 Fabric 的 JSON
        fabric_id = f"{mc_version}-Fabric"  # 你想要的名字格式
        log(f"正在将原版和 Fabric 合并为独立目录: {fabric_id}")

        # 读取原版 JSON
        vanilla_meta_path = self.paths.version_json(mc_version)
        vanilla_meta = json.loads(vanilla_meta_path.read_text(encoding="utf-8-sig"))

        # 深度合并
        merged_meta = copy.deepcopy(vanilla_meta)
        merged_meta["id"] = fabric_id

        # 合并 mainClass
        if "mainClass" in fabric_meta:
            merged_meta["mainClass"] = fabric_meta["mainClass"]

        # 合并 arguments
        if "arguments" in fabric_meta:
            merged_meta.setdefault("arguments", {})
            for key in ["game", "jvm"]:
                if key in fabric_meta["arguments"]:
                    merged_meta["arguments"].setdefault(key, []).extend(fabric_meta["arguments"][key])

        # 合并 minecraftArguments (旧版)
        if "minecraftArguments" in fabric_meta:
            old_args = merged_meta.get("minecraftArguments", "")
            new_args = fabric_meta["minecraftArguments"]
            merged_meta["minecraftArguments"] = f"{old_args} {new_args}".strip()

        # 合并 libraries
        if "libraries" in fabric_meta:
            merged_meta.setdefault("libraries", []).extend(fabric_meta["libraries"])

        # 清理 inheritsFrom 和 jar 字段，让它成为一个纯独立的版本
        merged_meta.pop("inheritsFrom", None)
        merged_meta.pop("jar", None)

        # 4. 创建新文件夹并写入文件
        v_dir = self.paths.version_dir(fabric_id)
        v_dir.mkdir(parents=True, exist_ok=True)

        # 写入合并后的 JSON
        meta_path = v_dir / f"{fabric_id}.json"
        meta_path.write_text(json.dumps(merged_meta, indent=2), encoding="utf-8")

        # 5. 复制原版 JAR 并重命名
        log("正在复制原版客户端 JAR...")
        src_jar = self.paths.client_jar(mc_version)
        dst_jar = self.paths.client_jar(fabric_id)
        if src_jar.is_file():
            shutil.copy2(src_jar, dst_jar)
        else:
            raise LauncherError("原版客户端 JAR 缺失，无法完成独立合并。")

        # 6. 下载 Fabric 依赖库
        libraries = fabric_meta.get("libraries", [])
        total = len(libraries)
        log(f"开始下载 {total} 个 Fabric 依赖库...")

        for i, lib in enumerate(libraries):
            check_cancel()
            name = lib.get("name", "")
            parts = name.split(":")
            if len(parts) < 3:
                continue
            group, artifact, version = parts[0], parts[1], parts[2]

            rel_path = f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"
            dest = self.paths.library_path(rel_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            if not dest.is_file():
                url = (lib.get("url") or "https://maven.fabricmc.net/").rstrip("/") + "/" + rel_path
                try:
                    urllib.request.urlretrieve(url, dest)
                except Exception as e:
                    check_cancel()
                    log(f"下载失败: {url} -> {e}")

            if callback:
                callback({"total": total, "current": i + 1, "percent": int((i + 1) / total * 100)})

        check_cancel()
        log(f"{fabric_id} 独立化安装完成！")
        return {"id": fabric_id, "type": "release"}  # 标记为 release 即可，走普通启动逻辑