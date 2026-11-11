from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .errors import LauncherError
from .net import USER_AGENT, download_file, get_json
from .progress import Progress

MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"

PROJECT_LABELS = {"mod": "模组", "resourcepack": "资源包"}

# CurseForge 的 classId：6 = Mods，12 = Resource Packs
CF_CLASS_IDS = {"mod": 6, "resourcepack": 12}
# CurseForge 的 modLoaderType
CF_LOADERS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CF_RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}

# 作者禁止第三方分发时 downloadUrl 为 null，回退到 CDN 规则
CF_CDN = "https://edge.forgecdn.net/files/{a}/{b}/{name}"

_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _facets(project_type: str, game_version: str | None, loader: str | None) -> str | None:
    groups: list[list[str]] = []
    if project_type:
        groups.append([f"project_type:{project_type}"])
    if game_version:
        groups.append([f"versions:{game_version}"])
    if loader and project_type == "mod":
        groups.append([f"categories:{loader}"])
    if not groups:
        return None
    return json.dumps(groups, separators=(",", ":"))


# ----------------------------------------------------------------------
# Modrinth
# ----------------------------------------------------------------------
def _modrinth_search(
    query: str,
    project_type: str,
    game_version: str | None,
    loader: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    params = {
        "query": query,
        "limit": str(max(1, min(limit, 50))),
        "offset": str(max(0, offset)),
        "index": "relevance",
    }
    facets = _facets(project_type, game_version, loader)
    if facets:
        params["facets"] = facets
    url = f"{MODRINTH_API}/search?" + urllib.parse.urlencode(params)
    data = get_json(url, headers=_HEADERS)
    hits = []
    for hit in data.get("hits") or []:
        hits.append(
            {
                "id": hit.get("project_id") or hit.get("slug") or "",
                "slug": hit.get("slug") or "",
                "title": hit.get("title") or "",
                "description": hit.get("description") or "",
                "author": hit.get("author") or "",
                "downloads": int(hit.get("downloads") or 0),
                "icon_url": hit.get("icon_url") or "",
                "categories": list(hit.get("categories") or []),
                "project_type": hit.get("project_type") or project_type,
                "source": "modrinth",
            }
        )
    return {"total": int(data.get("total_hits") or len(hits)), "hits": hits}


def _modrinth_versions(
    project_id: str,
    game_version: str | None,
    loader: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {}
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    if loader:
        params["loaders"] = json.dumps([loader])
    url = f"{MODRINTH_API}/project/{urllib.parse.quote(project_id)}/version"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = get_json(url, headers=_HEADERS)
    if not isinstance(data, list):
        raise LauncherError("Modrinth 返回了意外的版本数据")

    versions = []
    for item in data:
        files = item.get("files") or []
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            continue
        versions.append(
            {
                "id": str(item.get("id") or ""),
                "name": item.get("name") or item.get("version_number") or "",
                "version_number": item.get("version_number") or "",
                "game_versions": list(item.get("game_versions") or []),
                "loaders": list(item.get("loaders") or []),
                "date_published": item.get("date_published") or "",
                "downloads": int(item.get("downloads") or 0),
                "release_type": item.get("version_type") or "release",
                "dependencies": [
                    {
                        "project_id": str(dep.get("project_id") or ""),
                        "type": dep.get("dependency_type") or "",
                    }
                    for dep in item.get("dependencies") or []
                ],
                "file": {
                    "url": primary.get("url") or "",
                    "filename": primary.get("filename") or "",
                    "size": int(primary.get("size") or 0),
                    "sha1": (primary.get("hashes") or {}).get("sha1") or None,
                },
                "source": "modrinth",
            }
        )
    return versions


# ----------------------------------------------------------------------
# CurseForge
# ----------------------------------------------------------------------
def _cf_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise LauncherError("CurseForge 需要 API Key，请在「设置」里填写后重试。")
    return {**_HEADERS, "x-api-key": api_key}


def _cf_search(
    query: str,
    project_type: str,
    game_version: str | None,
    loader: str | None,
    limit: int,
    offset: int,
    api_key: str,
) -> dict[str, Any]:
    params = {
        "gameId": "432",
        "classId": str(CF_CLASS_IDS.get(project_type, 6)),
        "searchFilter": query,
        "sortField": "2",
        "sortOrder": "desc",
        "pageSize": str(max(1, min(limit, 50))),
        "index": str(max(0, offset)),
    }
    if game_version:
        params["gameVersion"] = game_version
    if loader and project_type == "mod":
        params["modLoaderType"] = str(CF_LOADERS.get(loader, 0))
    url = f"{CURSEFORGE_API}/mods/search?" + urllib.parse.urlencode(params)
    data = get_json(url, headers=_cf_headers(api_key))
    hits = []
    for item in data.get("data") or []:
        authors = item.get("authors") or []
        logo = item.get("logo") or {}
        hits.append(
            {
                "id": str(item.get("id") or ""),
                "slug": item.get("slug") or "",
                "title": item.get("name") or "",
                "description": item.get("summary") or "",
                "author": authors[0].get("name") if authors else "",
                "downloads": int(item.get("downloadCount") or 0),
                "icon_url": logo.get("thumbnailUrl") or "",
                "categories": [c.get("name") for c in item.get("categories") or [] if c.get("name")],
                "project_type": project_type,
                "source": "curseforge",
            }
        )
    pagination = data.get("pagination") or {}
    return {"total": int(pagination.get("totalCount") or len(hits)), "hits": hits}


def _cf_cdn_url(file_id: int, filename: str) -> str:
    return CF_CDN.format(a=file_id // 1000, b=file_id % 1000, name=filename)


def _cf_versions(
    project_id: str,
    game_version: str | None,
    loader: str | None,
    api_key: str,
) -> list[dict[str, Any]]:
    params = {"pageSize": "50"}
    if game_version:
        params["gameVersion"] = game_version
    if loader:
        params["modLoaderType"] = str(CF_LOADERS.get(loader, 0))
    url = f"{CURSEFORGE_API}/mods/{urllib.parse.quote(str(project_id))}/files?" + urllib.parse.urlencode(params)
    data = get_json(url, headers=_cf_headers(api_key))
    if not isinstance(data, dict):
        raise LauncherError("CurseForge 返回了意外的版本数据")

    versions = []
    for item in data.get("data") or []:
        filename = item.get("fileName") or ""
        file_id = int(item.get("id") or 0)
        download_url = item.get("downloadUrl") or (_cf_cdn_url(file_id, filename) if file_id and filename else "")
        if not download_url or not filename:
            continue
        game_versions = [str(v) for v in item.get("gameVersions") or []]
        loaders = [v for v in game_versions if v.lower() in CF_LOADERS]
        versions.append(
            {
                "id": str(file_id),
                "name": item.get("displayName") or filename,
                "version_number": item.get("displayName") or filename,
                "game_versions": [v for v in game_versions if v not in loaders],
                "loaders": loaders,
                "date_published": item.get("fileDate") or "",
                "downloads": 0,
                "release_type": CF_RELEASE_TYPES.get(int(item.get("releaseType") or 1), "release"),
                "dependencies": [
                    {
                        "project_id": str(dep.get("modId") or ""),
                        "type": "required" if int(dep.get("relationType") or 0) == 3 else "optional",
                    }
                    for dep in item.get("dependencies") or []
                ],
                "file": {
                    "url": download_url,
                    "filename": filename,
                    "size": int(item.get("fileLength") or 0),
                    "sha1": (item.get("hashes") or {}).get("sha1") or None,
                },
                "source": "curseforge",
            }
        )
    return versions


# ----------------------------------------------------------------------
# 公共接口
# ----------------------------------------------------------------------
def search(
    query: str,
    project_type: str = "mod",
    game_version: str | None = None,
    loader: str | None = None,
    limit: int = 20,
    offset: int = 0,
    source: str = "modrinth",
    api_key: str = "",
) -> dict[str, Any]:
    """搜索 Modrinth 或 CurseForge 上的模组/资源包。"""
    if source == "curseforge":
        return _cf_search(query, project_type, game_version, loader, limit, offset, api_key)
    return _modrinth_search(query, project_type, game_version, loader, limit, offset)


def project_versions(
    project_id: str,
    game_version: str | None = None,
    loader: str | None = None,
    source: str = "modrinth",
    api_key: str = "",
) -> list[dict[str, Any]]:
    """取某个项目的可选文件列表，第一条即推荐版本。

    排序规则：正式版优先于 beta/alpha，同级里按发布时间倒序。
    """
    if source == "curseforge":
        versions = _cf_versions(project_id, game_version, loader, api_key)
    else:
        versions = _modrinth_versions(project_id, game_version, loader)

    rank = {"release": 0, "beta": 1, "alpha": 2}
    versions.sort(
        key=lambda v: (
            rank.get(str(v.get("release_type") or "release"), 3),
            -_timestamp(v.get("date_published")),
        )
    )
    for index, version in enumerate(versions):
        version["recommended"] = index == 0
    return versions


def _timestamp(value: Any) -> float:
    """把 ISO8601 时间转成秒级时间戳，解析失败返回 0。"""
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, OSError, OverflowError):
        pass
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, OSError):
        return 0.0


def pick_version(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """推荐版本（列表首位）。"""
    return versions[0] if versions else None


def _required_dependencies(version: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dep
        for dep in version.get("dependencies") or []
        if dep.get("type") == "required" and dep.get("project_id")
    ]


def install(
    project_id: str,
    dest_dir: Path,
    project_type: str = "mod",
    game_version: str | None = None,
    loader: str | None = None,
    with_dependencies: bool = True,
    log: Callable[[str], None] | None = None,
    progress=None,
    source: str = "modrinth",
    api_key: str = "",
    chosen_version: dict[str, Any] | None = None,
    cancel_event=None,
) -> dict[str, Any]:
    """下载并安装到目标目录；chosen_version 非空时直接安装该文件。"""
    def say(message: str) -> None:
        if log is not None:
            try:
                log(message)
            except Exception:
                pass

    target = chosen_version
    if target is None:
        versions = project_versions(project_id, game_version, loader, source, api_key)
        target = pick_version(versions)
    if target is None:
        suffix = f"（{game_version}" if game_version else ""
        if loader and game_version:
            suffix += f" / {loader}"
        suffix += "）" if suffix else ""
        raise LauncherError(f"没有找到匹配的版本{suffix}，可能不支持当前游戏版本。")

    dest_dir.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []

    # 预先算好总大小，进度条才有百分比
    plan: list[dict[str, Any]] = [target]
    if with_dependencies:
        for dep in _required_dependencies(target):
            try:
                dep_versions = project_versions(
                    dep["project_id"], game_version, loader, source, api_key
                )
                dep_target = pick_version(dep_versions)
                if dep_target is None:
                    say(f"[!] 依赖 {dep['project_id']} 没有匹配版本，已跳过")
                    continue
                if (dest_dir / str(dep_target["file"]["filename"])).exists():
                    say(f"[*] 依赖已存在 {dep_target['file']['filename']}")
                    continue
                plan.append(dep_target)
            except LauncherError:
                raise
            except Exception as exc:
                say(f"[!] 依赖读取失败：{exc}")

    total_size = sum(int(v["file"].get("size") or 0) for v in plan)
    progress_bar = Progress(
        "下载内容",
        total_size,
        enabled=False,
        callback=progress,
        cancel_event=cancel_event,
    )

    def fetch(version: dict[str, Any]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise LauncherError("操作已取消")
        file = version["file"]
        filename = str(file.get("filename") or "")
        if not filename:
            raise LauncherError("该版本没有可下载文件")
        dest = dest_dir / filename
        say(f"[*] 下载 {filename}")
        download_file(
            file["url"],
            dest,
            file.get("sha1"),
            file.get("size") or None,
            progress_bar,
        )
        installed.append(filename)

    try:
        for item in plan:
            fetch(item)
    finally:
        progress_bar.finish()

    say(f"[+] 已安装 {len(installed)} 个文件到 {dest_dir}")
    return {
        "files": installed,
        "dir": str(dest_dir),
        "version": target.get("version_number") or target.get("name") or "",
        "type": project_type,
        "source": source,
    }
