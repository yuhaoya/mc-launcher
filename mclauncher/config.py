from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import default_config_dir
from .util import read_json, write_json_atomic

DEFAULT_CONFIG: dict[str, Any] = {
    "game_dir": None,
    "java_path": None,
    "memory_mb": 4096,
    "client_id": None,
    "msa": None,
    "offline_name": "Player",
}


class Config:
    """简单的 JSON 配置，保存在配置目录（默认 %APPDATA%\\mclauncher）。"""

    def __init__(self, config_dir: Path | None = None):
        self.dir = (config_dir or default_config_dir()).expanduser().resolve()
        self.path = self.dir / "config.json"
        data = read_json(self.path, {})
        self.data: dict[str, Any] = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            self.data.update(data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self) -> None:
        write_json_atomic(self.path, self.data)

    def clear_msa(self) -> None:
        self.data["msa"] = None
        self.save()
