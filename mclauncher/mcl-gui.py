from __future__ import annotations

import os
import sys

# 针对 PyInstaller 打包后的环境，手动将 pywin32_system32 添加到 DLL 搜索路径
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    pywin32_path = os.path.join(base_path, 'pywin32_system32')
    if os.path.exists(pywin32_path):
        os.environ['PATH'] = pywin32_path + os.pathsep + os.environ['PATH']

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mclauncher.gui.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
