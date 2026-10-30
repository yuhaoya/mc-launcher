from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any, Callable
import copy,json
import urllib.request
import shutil
import subprocess
import os

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
        self.repo = VersionRepository(self.paths, mirror_func=self.apply_mirror)

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
            "isolate_versions": bool(self.config.get("isolate_versions") or False),
            "mirror_source": self.config.get("mirror_source") or "official",
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
        if "mirror_source" in values:
            self.config.set("mirror_source", values["mirror_source"])
        self.config.save()
        return self.settings()

    # ------------------------------------------------------------------
    # 实例独立设置 (Instance Settings)
    # ------------------------------------------------------------------
    def get_instance_settings(self, version_id: str) -> dict[str, Any]:
        """获取指定版本的独立设置，如果没有则返回空字典"""
        all_instances = self.config.get("instance_settings") or {}
        return all_instances.get(version_id, {})

    def save_instance_settings(self, version_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """保存指定版本的独立设置"""
        all_instances = self.config.get("instance_settings") or {}

        # 如果传入空字典，表示删除该实例的独立设置（恢复全局设置）
        if not values:
            all_instances.pop(version_id, None)
        else:
            all_instances[version_id] = values

        self.config.set("instance_settings", all_instances)
        self.config.save()
        return self.get_instance_settings(version_id)

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

    def apply_mirror(self, url: str) -> str:
        """将官方 URL 替换为国内镜像"""
        if self.config.get("mirror_source") != "bmclapi":
            return url
        replacements = {
            "https://launchermeta.mojang.com": "https://bmclapi2.bangbang93.com",
            "https://piston-meta.mojang.com": "https://bmclapi2.bangbang93.com",
            "https://piston-data.mojang.com": "https://bmclapi2.bangbang93.com",
            "https://libraries.minecraft.net": "https://bmclapi2.bangbang93.com/maven",
            "https://resources.download.minecraft.net": "https://bmclapi2.bangbang93.com/assets",
            "https://meta.fabricmc.net": "https://bmclapi2.bangbang93.com/fabric-meta",
            "https://maven.fabricmc.net": "https://bmclapi2.bangbang93.com/maven",
            "https://maven.minecraftforge.net": "https://bmclapi2.bangbang93.com/maven",
            "https://files.minecraftforge.net": "https://bmclapi2.bangbang93.com/maven",
        }
        for official, mirror in replacements.items():
            url = url.replace(official, mirror)
        return url

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
            mirror_func=self.apply_mirror,
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
        # 读取实例独立配置，如果没有则使用全局配置
        instance_conf = self.get_instance_settings(version_id)

        # 优先使用调用时传入的参数 -> 实例配置 -> 全局配置
        final_memory = memory_mb or instance_conf.get("memory_mb") or self.config.get("memory_mb") or 4096
        final_java = java_path or instance_conf.get("java_path") or self.config.get("java_path")
        final_isolate = instance_conf.get("isolate_versions")
        if final_isolate is None:
            final_isolate = bool(self.config.get("isolate_versions") or False)

        java = Path(final_java) if final_java else None
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
        memory = parse_memory_mb(final_memory)
        isolate = bool(final_isolate)
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
            elif key == "assetIndex":
                # 👇 核心修复：原版的资源索引（如 "5"）永远优先于子版本的 legacy
                if "assetIndex" not in merged or merged["assetIndex"].get("id") == "legacy":
                    merged["assetIndex"] = value
            elif key == "assets":
                # 👇 核心修复：防止 assets 被覆盖
                if "assets" not in merged or merged["assets"] == "legacy":
                    merged["assets"] = value
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
        import copy
        import time

        def check_cancel():
            if cancel_event and cancel_event.is_set():
                raise LauncherError("安装已取消")

        def log(msg):
            if log_callback:
                log_callback(f"[*] {msg}")

        def download_file_with_fallback(url: str, dest: Path):
            """带降级逻辑的下载器：先尝试镜像，失败则回退到官方"""
            # 生成候选 URL 列表（镜像源 + 原始官方源）
            candidates = []
            mirror_url = self.apply_mirror(url)
            if mirror_url != url:
                candidates.append(mirror_url)
            if url not in candidates:
                candidates.append(url)

            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            last_err = None

            for candidate in candidates:
                try:
                    req = urllib.request.Request(candidate, headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with open(dest, 'wb') as f:
                            f.write(resp.read())
                    return  # 下载成功，直接返回
                except Exception as e:
                    last_err = e
                    log(f"下载失败 ({candidate})：{e}")
                    if candidate == candidates[-1]:
                        break
                    log("正在降级切换至备用源重试...")
                    time.sleep(1)

            raise last_err

        check_cancel()

        # 1. 检查原版是否已安装，并记录状态
        original_existed = is_installed(self.paths, mc_version)

        if not original_existed:
            log(f"检测到原版 {mc_version} 未安装，准备自动下载...")
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
        else:
            log(f"原版 {mc_version} 已存在，直接进行合并。")

        # 2. 获取 Fabric 数据（这里也应用降级逻辑）
        log(f"正在获取 Fabric {mc_version} 的版本信息...")
        try:
            # 先尝试镜像，再尝试官方
            urls_to_try = [
                self.apply_mirror(f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"),
                f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
            ]
            urls_to_try = list(dict.fromkeys(urls_to_try))  # 去重

            data = None
            for url in urls_to_try:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode())
                    break
                except Exception:
                    continue
            if not data:
                raise Exception("所有源均无法获取 Fabric 列表")

            loader_version = data[0]["loader"]["version"]

            # 获取 Profile 同样降级
            profile_urls = [
                self.apply_mirror(
                    f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/profile/json"),
                f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/profile/json"
            ]
            profile_urls = list(dict.fromkeys(profile_urls))

            fabric_meta = None
            for url in profile_urls:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        fabric_meta = json.loads(resp.read().decode())
                    break
                except Exception:
                    continue
            if not fabric_meta:
                raise Exception("所有源均无法获取 Fabric Profile")

        except Exception as e:
            check_cancel()
            raise LauncherError(f"获取 Fabric 信息失败: {e}")

        check_cancel()

        # 3. 独立化合并
        fabric_id = f"{mc_version}-Fabric"
        log(f"正在将原版和 Fabric 合并为独立目录: {fabric_id}")

        vanilla_meta_path = self.paths.version_json(mc_version)
        vanilla_meta = json.loads(vanilla_meta_path.read_text(encoding="utf-8-sig"))

        merged_meta = copy.deepcopy(vanilla_meta)
        merged_meta["id"] = fabric_id

        if "mainClass" in fabric_meta:
            merged_meta["mainClass"] = fabric_meta["mainClass"]

        if "arguments" in fabric_meta:
            merged_meta.setdefault("arguments", {})
            for key in ["game", "jvm"]:
                if key in fabric_meta["arguments"]:
                    merged_meta["arguments"].setdefault(key, []).extend(fabric_meta["arguments"][key])

        if "minecraftArguments" in fabric_meta:
            old_args = merged_meta.get("minecraftArguments", "")
            new_args = fabric_meta["minecraftArguments"]
            merged_meta["minecraftArguments"] = f"{old_args} {new_args}".strip()

        if "libraries" in fabric_meta:
            merged_meta.setdefault("libraries", []).extend(fabric_meta["libraries"])

        merged_meta.pop("inheritsFrom", None)
        merged_meta.pop("jar", None)

        # 4. 写入独立版本
        v_dir = self.paths.version_dir(fabric_id)
        v_dir.mkdir(parents=True, exist_ok=True)
        meta_path = v_dir / f"{fabric_id}.json"
        meta_path.write_text(json.dumps(merged_meta, indent=2), encoding="utf-8")

        # 5. 复制核心 JAR
        log("正在复制原版客户端 JAR...")
        src_jar = self.paths.client_jar(mc_version)
        dst_jar = self.paths.client_jar(fabric_id)
        if src_jar.is_file():
            shutil.copy2(src_jar, dst_jar)
        else:
            raise LauncherError("原版客户端 JAR 缺失。")

        # 6. 下载 Fabric 依赖库（应用降级下载）
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
                official_url = (lib.get("url") or "https://maven.fabricmc.net/").rstrip("/") + "/" + rel_path
                try:
                    # 👇 使用自动降级的下载器
                    download_file_with_fallback(official_url, dest)
                except Exception as e:
                    check_cancel()
                    log(f"最终下载失败: {official_url} -> {e}")

            if callback:
                callback({"total": total, "current": i + 1, "percent": int((i + 1) / total * 100)})

        # 7. 核心清理
        if not original_existed:
            log(f"清理临时原版文件夹: {mc_version}")
            shutil.rmtree(self.paths.version_dir(mc_version), ignore_errors=True)

        log(f"{fabric_id} 独立化安装完成！")
        return {"id": fabric_id, "type": "release"}

    def install_forge(
            self,
            mc_version: str,
            callback: ProgressCallback | None = None,
            log_callback: LogCallback | None = None,
            cancel_event: threading.Event | None = None
    ) -> dict[str, Any]:
        import copy
        import shutil

        def check_cancel():
            if cancel_event and cancel_event.is_set():
                raise LauncherError("安装已取消")

        def log(msg):
            if log_callback:
                log_callback(f"[*] {msg}")

        check_cancel()

        # 1. 检查原版是否存在
        original_existed = is_installed(self.paths, mc_version)

        if not original_existed:
            log(f"检测到原版 {mc_version} 未安装，准备自动下载...")
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
        else:
            log(f"原版 {mc_version} 已存在，直接进行合并。")

        check_cancel()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # 2. 获取推荐的 Forge 版本
        # 2. 获取推荐的 Forge 版本
        try:
            promo_url = self.apply_mirror(
                "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json")
            req = urllib.request.Request(promo_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=30) as response:
                promos = json.loads(response.read().decode())

            forge_version = promos.get("promos", {}).get(f"{mc_version}-recommended",
                                                         promos.get("promos", {}).get(f"{mc_version}-latest"))
            if not forge_version:
                raise LauncherError(f"未找到适用于 {mc_version} 的 Forge 版本")
        except Exception as e:
            raise LauncherError(f"获取 Forge 版本失败: {e}")

        log(f"找到推荐版本: {forge_version}")

        # 3. 下载 installer.jar
        installer_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
        installer_url = self.apply_mirror(installer_url)
        installer_jar = self.paths.cache_dir / f"forge-{mc_version}-{forge_version}-installer.jar"
        installer_jar.parent.mkdir(parents=True, exist_ok=True)

        if not installer_jar.is_file():
            log("正在下载 Forge Installer...")
            try:
                installer_url = self.apply_mirror(installer_url)
                req = urllib.request.Request(installer_url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as response:
                    with open(installer_jar, 'wb') as f:
                        f.write(response.read())
            except Exception as e:
                raise LauncherError(f"下载 Forge Installer 失败: {e}")

        check_cancel()

        # 4. 获取 Java 并执行安装
        log("正在准备 Java 环境...")
        vanilla_meta = self.repo.meta(mc_version)
        java = ensure_java(
            vanilla_meta, self.paths, allow_install=True,
            stream=io.StringIO(), callback=callback, cancel_event=cancel_event
        )

        log("正在执行 Forge 安装器（可能需要几分钟）...")

        profiles_file = self.paths.game_dir / "launcher_profiles.json"
        if not profiles_file.is_file():
            profiles_file.write_text("{}", encoding="utf-8")

        cmd = [str(java), "-jar", str(installer_jar), "--installClient"]

        env = os.environ.copy()
        java_dir = str(Path(java).parent)
        env["PATH"] = java_dir + os.pathsep + env.get("PATH", "")

        process = subprocess.Popen(
            cmd,
            cwd=str(self.paths.game_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            env=env
        )

        for line in process.stdout:
            check_cancel()
            line = line.strip()
            if line:
                log(line)

        process.wait()
        if process.returncode != 0:
            raise LauncherError(f"Forge 安装器执行失败，退出码: {process.returncode}")

        check_cancel()

        # 5. 独立化处理
        log("正在创建独立化 Forge 版本...")
        forge_raw_id = f"{mc_version}-forge-{forge_version}"
        forge_json_path = self.paths.version_json(forge_raw_id)

        if not forge_json_path.is_file():
            raise LauncherError("Forge 安装器执行完毕，但未找到生成的版本 JSON。")

        forge_meta = json.loads(forge_json_path.read_text(encoding="utf-8-sig"))

        # 深度合并
        merged_meta = copy.deepcopy(vanilla_meta)
        target_id = f"{mc_version}-Forge"
        merged_meta["id"] = target_id

        if "mainClass" in forge_meta:
            merged_meta["mainClass"] = forge_meta["mainClass"]

        if "arguments" in forge_meta:
            merged_meta.setdefault("arguments", {})
            for key in ["game", "jvm"]:
                if key in forge_meta["arguments"]:
                    merged_meta["arguments"].setdefault(key, []).extend(forge_meta["arguments"][key])

        if "minecraftArguments" in forge_meta:
            old_args = merged_meta.get("minecraftArguments", "")
            new_args = forge_meta["minecraftArguments"]
            merged_meta["minecraftArguments"] = f"{old_args} {new_args}".strip()

        if "libraries" in forge_meta:
            merged_meta.setdefault("libraries", []).extend(forge_meta["libraries"])

        # 保护原版资源索引
        if "assetIndex" in forge_meta:
            if "assetIndex" not in merged_meta or merged_meta["assetIndex"].get("id") == "legacy":
                merged_meta["assetIndex"] = forge_meta["assetIndex"]

        merged_meta.pop("inheritsFrom", None)
        merged_meta.pop("jar", None)

        # 6. 写入独立版本并复制 JAR
        target_dir = self.paths.version_dir(target_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_json_path = target_dir / f"{target_id}.json"
        target_json_path.write_text(json.dumps(merged_meta, indent=2), encoding="utf-8")

        log("正在复制原版客户端 JAR...")
        src_jar = self.paths.client_jar(mc_version)
        dst_jar = self.paths.client_jar(target_id)
        if src_jar.is_file():
            shutil.copy2(src_jar, dst_jar)
        else:
            raise LauncherError("原版客户端 JAR 缺失。")

        # 👇 7. 清理中间产物与原版
        if forge_raw_id != mc_version and forge_raw_id != target_id:
            log(f"清理中间产物: {forge_raw_id}")
            shutil.rmtree(self.paths.version_dir(forge_raw_id), ignore_errors=True)

        if not original_existed:
            log(f"清理临时原版文件夹: {mc_version}")
            shutil.rmtree(self.paths.version_dir(mc_version), ignore_errors=True)

        log(f"{target_id} 独立化安装完成！")
        return {"id": target_id, "type": "release"}