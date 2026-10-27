from __future__ import annotations

import shutil
import uuid
from pathlib import Path

# 说明：在当前 Windows 沙箱里，用 mode=0o700 创建的目录（tempfile 默认）会出现
# 访问被拒的 ACL，因此测试统一使用普通权限的临时目录。
BASE = Path(__file__).resolve().parent.parent / ".test-tmp"


def make_temp_dir() -> Path:
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / f"t-{uuid.uuid4().hex[:10]}"
    path.mkdir()
    return path


def remove_temp_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
