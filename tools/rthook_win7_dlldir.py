"""自定义运行时钩子：在 PyInstaller 官方钩子之前打补丁。

Win7 SP1 若没装 KB2533623，系统缺少 ``AddDllDirectory``，Python 3.8 的
``os.add_dll_directory()`` 会直接抛 ``OSError: [WinError 127]``。
官方钩子 ``pyi_rth_pyside6`` 会在 ``create_embedded_qt_conf()`` 里导入 PySide6，
而 PySide6 6.1.3 的 ``_setupQtDirectories()`` 正好调用这个 API；
``pyimod04_pywin32`` 也依赖它。自定义运行时钩子先于所有官方钩子执行。

兜底方案：把目录加进 ``PATH``（Win7 的 Loader 仍按 PATH 搜索 DLL），
并返回一个带 ``close()`` 的假句柄，保持与官方 API 兼容。

注意：扩展模块（.pyd）的加载标志写死在 python38.dll 里，无法从这里修改，
由 spec 中的 ``patch_cpython_dynload_flags()`` 在构建时替换。
"""

import os
import sys


class _DllDirectoryHandle:
    def close(self) -> None:
        pass

    def __enter__(self) -> "_DllDirectoryHandle":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _patch_add_dll_directory() -> None:
    if sys.platform != "win32":
        return

    original = getattr(os, "add_dll_directory", None)
    if original is None:
        return

    # 测试用：MCL_FORCE_DLLDIR_FALLBACK=1 强制走兜底，便于在 Win8+ 上复现 Win7 行为。
    forced = os.environ.get("MCL_FORCE_DLLDIR_FALLBACK") == "1"

    # 能正常调用就不改动行为（Win8+ / 打过补丁的 Win7）。
    if not forced:
        try:
            probe = original(getattr(sys, "_MEIPASS", sys.prefix))
        except OSError:
            pass
        except Exception:
            pass
        else:
            try:
                probe.close()
            except Exception:
                pass
            return

    def add_dll_directory(path):  # type: ignore[no-untyped-def]
        directory = os.fspath(path)
        if os.path.isdir(directory):
            current = os.environ.get("PATH", "")
            parts = current.split(os.pathsep) if current else []
            if directory not in parts:
                os.environ["PATH"] = directory + (os.pathsep + current if current else "")
        return _DllDirectoryHandle()

    os.add_dll_directory = add_dll_directory  # type: ignore[assignment]


_patch_add_dll_directory()
