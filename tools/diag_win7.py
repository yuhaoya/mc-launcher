"""Win7 启动诊断（针对 WinError 87 / _socket 加载失败）。

只做探测，不导入 Qt / socket 顶层，避免重复触发崩溃。
构建：python -m PyInstaller --noconfirm --onefile --console --name mcl-diag-win7 ...
"""
from __future__ import annotations

import ctypes
import os
import platform
import sys

LINES: list[str] = []


def say(text: str = "") -> None:
    LINES.append(text)
    try:
        print(text, flush=True)
    except Exception:
        pass


def k32():
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    return dll


def has_export(name: str) -> bool:
    try:
        d = k32()
        d.GetProcAddress.restype = ctypes.c_void_p
        d.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        return bool(d.GetProcAddress(ctypes.c_void_p(d._handle), name.encode()))
    except Exception:
        return False


def load(path: str, flags: int) -> tuple[bool, int]:
    try:
        d = k32()
        d.LoadLibraryExW.restype = ctypes.c_void_p
        d.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
        ctypes.set_last_error(0)
        handle = d.LoadLibraryExW(path, None, flags)
        err = ctypes.get_last_error()
        return bool(handle), err
    except Exception as exc:
        return False, getattr(exc, "winerror", -1)


def main() -> int:
    win = sys.getwindowsversion()
    meipass = getattr(sys, "_MEIPASS", "") or "(无)"

    say("=" * 70)
    say("Micalith Launcher · Win7 诊断 (WinError 87)")
    say("=" * 70)
    say(f"Python      : {sys.version.split()[0]}")
    say(f"Windows     : {win.major}.{win.minor} build {win.build}")
    say(f"platform    : {platform.platform()}")
    say(f"64bit       : {sys.maxsize > 2**32}")
    say(f"frozen      : {getattr(sys, 'frozen', False)}")
    say(f"_MEIPASS    : {meipass}")
    say(f"exe         : {sys.executable}")
    say("")

    say("-" * 70)
    say("1. 关键内核 API")
    for fn in ("AddDllDirectory", "RemoveDllDirectory", "SetDefaultDllDirectories"):
        say(f"   {fn:<26} {'有' if has_export(fn) else '缺失'}")
    say(f"   os.add_dll_directory 可用 : {hasattr(os, 'add_dll_directory')}")
    say(f"   已被本程序替换            : {getattr(os.add_dll_directory, '__module__', '?') == 'rthook_win7_dlldir'}")
    say("")

    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    sys32 = os.path.join(sysroot, "System32")
    say("-" * 70)
    say(f"2. 系统 UCRT（{sys32}）")
    for n in ("ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll",
              "api-ms-win-crt-string-l1-1-0.dll", "api-ms-win-crt-heap-l1-1-0.dll"):
        p = os.path.join(sys32, n)
        say(f"   {n:<42} {'存在' if os.path.exists(p) else '缺失'}")
    say("")

    if meipass != "(无)":
        say("-" * 70)
        say("3. 解包目录中的 CRT / 运行库")
        try:
            entries = sorted(os.listdir(meipass))
        except OSError as exc:
            entries = []
            say(f"   无法列出：{exc}")
        shown = 0
        for n in entries:
            low = n.lower()
            if low.endswith(".dll") and ("ucrt" in low or low.startswith("api-ms-win") or "vcruntime" in low):
                say(f"   {n}")
                shown += 1
        if not shown:
            say("   （无）")
        dyn = os.path.join(meipass, "lib-dynload")
        say(f"   lib-dynload 目录 : {'存在' if os.path.isdir(dyn) else '不存在'}")
        say("")

    # 定位 _socket.pyd
    candidates = []
    if meipass != "(无)":
        candidates.append(os.path.join(meipass, "_socket.pyd"))
        candidates.append(os.path.join(meipass, "lib-dynload", "_socket.pyd"))
    target = next((p for p in candidates if os.path.isfile(p)), "")

    say("-" * 70)
    say("4. 用不同的 LoadLibraryEx 标志加载 _socket.pyd")
    if not target:
        say("   找不到 _socket.pyd")
    else:
        say(f"   路径: {target}")
        flags_map = [
            ("0 (默认)", 0),
            ("LOAD_WITH_ALTERED_SEARCH_PATH", 0x00000008),
            ("LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|DEFAULT_DIRS", 0x00000100 | 0x00001000),
            ("LOAD_LIBRARY_SEARCH_USER_DIRS|DEFAULT_DIRS", 0x00000400 | 0x00001000),
        ]
        for label, flag in flags_map:
            ok, err = load(target, flag)
            say(f"   [{ 'ok ' if ok else 'FAIL'}] {label:<46} GetLastError={err}")
    say("")

    say("-" * 70)
    say("5. 实际 import 测试")
    for mod in ("ctypes", "_socket", "socket", "ssl"):
        try:
            __import__(mod)
        except Exception as exc:
            code = getattr(exc, "winerror", "")
            say(f"   [FAIL] {mod:<10} {type(exc).__name__}: {exc} {('winerror=' + str(code)) if code != '' else ''}")
        else:
            say(f"   [ ok ] {mod}")
    say("")

    say("=" * 70)
    say("请把以上全部内容发回（或发 %USERPROFILE%\\mcl-diag.txt）")
    say("=" * 70)

    try:
        out = os.path.join(os.path.expanduser("~"), "mcl-diag.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(LINES))
        say(f"已保存: {out}")
    except OSError as exc:
        say(f"保存失败: {exc}")

    try:
        input("\n按回车退出…")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
