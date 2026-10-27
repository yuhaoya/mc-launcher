#!/usr/bin/env python3
"""开发时直接运行：python mcl.py ..."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mclauncher.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
