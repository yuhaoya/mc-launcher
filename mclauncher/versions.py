from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TextIO, Callable

from .errors import LauncherError
from .net import download_file, get_json
from .paths import Paths
from .util import read_json, write_json_atomic

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
MANIFEST_TTL = 600  # 10 分钟

ALIASES = {
    "latest": "release",
    "latest-release": "release",
    "release": "release",
    "正式版": "release",
    "latest-snapshot": "snapshot",
    "snapshot": "snapshot",
    "快照": "snapshot",
}


class VersionRepository:
    def __init__(self, paths: Paths, stream: TextIO | None = None, mirror_func: Callable[[str], str] | None = None):
        self.paths = paths
        self.stream = stream
        self.mirror_func = mirror_func or (lambda url: url)

    # ------------------------------------------------------------------
    def manifest(self, force: bool = False) -> dict[str, Any]:
        cache = self.paths.cache_dir / "version_manifest_v2.json"
        if not force and cache.is_file() and time.time() - cache.stat().st_mtime < MANIFEST_TTL:
            data = read_json(cache)
            if isinstance(data, dict) and "versions" in data:
                return data
        try:
            url = self.mirror_func(MANIFEST_URL)
            data = get_json(url)
            if not isinstance(data, dict) or "versions" not in data:
                raise LauncherError("Mojang 返回的版本清单格式异常")
            write_json_atomic(cache, data)
            return data
        except Exception as exc:
            if cache.is_file():
                data = read_json(cache)
                if isinstance(data, dict) and "versions" in data:
                    if self.stream:
                        print(f"[!] 获取版本清单失败，使用本地缓存：{exc}", file=self.stream)
                    return data
            raise LauncherError(f"无法获取 Minecraft 版本清单：{exc}") from exc

    def resolve(self, version: str) -> dict[str, Any]:
        manifest = self.manifest()
        latest = manifest.get("latest", {})
        version = version.strip()
        key = version.lower()
        if key in ALIASES:
            version = latest.get(ALIASES[key], "")
        for entry in manifest.get("versions", []):
            if entry.get("id") == version:
                return entry
        raise LauncherError(
            f"找不到版本 {version!r}。用 `mcl versions` 查看可安装的版本，"
            f"或使用 latest / latest-snapshot。"
        )

    # ------------------------------------------------------------------
    def meta(self, version_id: str, force: bool = False) -> dict[str, Any]:
        local = self.paths.version_json(version_id)
        if local.is_file() and not force:
            data = read_json(local)
            if isinstance(data, dict) and data.get("id") == version_id:
                return data
        entry = self.resolve(version_id)
        url = self.mirror_func(entry["url"])
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(local.name + ".download")
        try:
            download_file(url, tmp, entry.get("sha1"), entry.get("size"), retries=4)
            data = read_json(tmp)
            if not isinstance(data, dict) or data.get("id") != version_id:
                raise LauncherError(f"版本 {version_id} 的 JSON 无效")
            tmp.replace(local)
            return data
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    def ensure_meta_file(self, version_id: str, force: bool = False) -> Path:
        self.meta(version_id, force=force)
        return self.paths.version_json(version_id)

    def installed_versions(self) -> list[str]:
        if not self.paths.versions.is_dir():
            return []
        return sorted(
            child.name
            for child in self.paths.versions.iterdir()
            if child.is_dir() and (child / f"{child.name}.json").is_file()
        )
