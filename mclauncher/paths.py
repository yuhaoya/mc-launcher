from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_game_dir() -> Path:
    """默认使用官方启动器的 .minecraft 目录，保证已安装的内容可以直接复用。"""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / ".minecraft"
    return Path.home() / ".minecraft"


def default_config_dir() -> Path:
    env = os.environ.get("MCL_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "mclauncher"
    return Path.home() / ".config" / "mclauncher"


@dataclass(frozen=True)
class Paths:
    game_dir: Path
    config_dir: Path

    @property
    def versions(self) -> Path:
        return self.game_dir / "versions"

    @property
    def libraries(self) -> Path:
        return self.game_dir / "libraries"

    @property
    def assets(self) -> Path:
        return self.game_dir / "assets"

    @property
    def assets_indexes(self) -> Path:
        return self.assets / "indexes"

    @property
    def assets_objects(self) -> Path:
        return self.assets / "objects"

    @property
    def assets_virtual(self) -> Path:
        return self.assets / "virtual"

    @property
    def runtime(self) -> Path:
        return self.game_dir / "runtime"

    @property
    def logs(self) -> Path:
        return self.game_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.config_dir / "cache"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    def version_dir(self, version_id: str) -> Path:
        return self.versions / version_id

    def version_json(self, version_id: str) -> Path:
        return self.version_dir(version_id) / f"{version_id}.json"

    def client_jar(self, version_id: str) -> Path:
        return self.version_dir(version_id) / f"{version_id}.jar"

    def natives_dir(self, version_id: str) -> Path:
        return self.version_dir(version_id) / "natives"

    def library_path(self, relative: str) -> Path:
        return self.libraries / Path(*relative.split("/"))

    def describe(self) -> str:
        lines = [
            f"游戏目录   : {self.game_dir}",
            f"配置目录   : {self.config_dir}",
            f"版本目录   : {self.versions}",
            f"依赖库目录 : {self.libraries}",
            f"资源目录   : {self.assets}",
            f"Java 运行时: {self.runtime}",

        ]
        lines.append(f"版本隔离   : {'开' if isolate else '关'}")
        return "\n".join(lines)
    # ---------------- 版本隔离 ----------------
    def instance_game_dir(self, version_id: str, isolate: bool = False) -> Path:
        """版本实际使用的 gameDir：隔离时指向 versions/<id>，否则回落到根目录。"""
        if isolate:
            return self.version_dir(version_id)
        return self.game_dir

    def instance_dir(self, version_id: str) -> Path:
        """版本隔离目录（即使不启用隔离也方便读写这里的子目录）。"""
        return self.version_dir(version_id)

    def instance_subdir(self, version_id: str, name: str) -> Path:
        """版本目录下的某个子目录，比如 mods / saves / resourcepacks。"""
        return self.instance_dir(version_id) / name

    # 便捷属性：只读，用于构建路径
    @property
    def shared_mods(self) -> Path:
        return self.game_dir / "mods"

    @property
    def shared_saves(self) -> Path:
        return self.game_dir / "saves"
