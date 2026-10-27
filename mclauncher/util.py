from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_matches(path: Path, sha1: str | None = None, size: int | None = None) -> bool:
    """快速判断本地文件是否完整。

    有 size 时只比较大小（避免每次启动都哈希几百 MB 资源）；
    没有 size 但有 sha1 时计算哈希。
    """
    try:
        if not path.is_file():
            return False
        if size is not None:
            return path.stat().st_size == size
        if sha1:
            return sha1_file(path) == sha1
    except OSError:
        return False
    return True


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def human_size(num: float) -> str:
    """把字节数格式化成人类可读的字符串。"""
    if num is None:
        return "?"
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(num)} B"
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} GB"


def format_speed(bytes_per_sec: float) -> str:
    return f"{human_size(bytes_per_sec)}/s"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds > 24 * 3600:
        return "--:--"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def parse_memory_mb(text: str | int) -> int:
    """解析 '4096' / '4G' / '512M' 这类内存写法，返回 MB。"""
    if isinstance(text, int):
        value = text
        unit = "M"
    else:
        s = str(text).strip().upper().replace(" ", "")
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([MGT]?)B?", s)
        if not match:
            raise ValueError(f"无法识别的内存大小: {text}")
        value = float(match.group(1))
        unit = match.group(2) or "M"
    multiplier = {"M": 1, "G": 1024, "T": 1024 * 1024}[unit]
    mb = int(value * multiplier)
    if mb < 512:
        raise ValueError("内存至少需要 512MB")
    return mb


def link_or_copy(src: Path, dst: Path) -> None:
    """优先硬链接，失败则复制。用于 legacy 资源映射。"""
    ensure_dir(dst.parent)
    try:
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def shorten_path(path: Path, limit: int = 80) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return "..." + text[-(limit - 3):]
