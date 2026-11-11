"""Windows 7 打包入口。

Win7 的 DLL 目录兼容处理放在自定义运行时钩子
``tools/rthook_win7_dlldir.py`` 里——它先于 PyInstaller 官方钩子和本脚本执行，
因此 PySide6 / pywin32 初始化时的 ``os.add_dll_directory()`` 已被替换。
"""
from __future__ import annotations

import sys

from mclauncher.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
