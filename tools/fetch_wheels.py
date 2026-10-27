"""Download and unpack the GUI/TUI wheels without invoking pip.

pip cannot use temporary directories under the current Windows sandbox
(the DSH file policy denies access to its mode-0700 temp dirs), so this
script resolves wheels from PyPI, downloads them into .wheels, and unpacks
them straight into the venv's site-packages.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = sys.version_info
CACHE = ROOT / ".wheels"
SITE = ROOT / ".venv" / "Lib" / "site-packages"
SCRIPTS = ROOT / ".venv" / "Scripts"

PACKAGES = [
    "PySide6-Essentials",
    "shiboken6",
    "PySide6-Fluent-Widgets",
    "PySideSix-Frameless-Window",
    "darkdetect",
    "textual",
    "rich",
    "markdown-it-py",
    "mdit-py-plugins",
    "platformdirs",
    "typing-extensions",
    "linkify-it-py",
    "uc-micro-py",
    "pygments",
    "mdurl",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "setuptools",
    "packaging",
]


def wheel_rank(filename: str) -> tuple[int, ...]:
    """Prefer a Windows x64 CPython 3.12 wheel, then abi3, then pure py3."""
    name = filename.lower()
    if "win_amd64" in name:
        platform_score = 40
    elif name.endswith("-none-any.whl"):
        platform_score = 10
    else:
        return ()
    py_score = 0
    if f"cp{VERSION.major}{VERSION.minor}" in name:
        py_score = 30
    elif "abi3" in name:
        py_score = 20
    elif "py3" in name or "py2.py3" in name:
        py_score = 15
    else:
        return ()
    return (platform_score, py_score)


def pick_wheel(files: list[dict]) -> dict:
    candidates = [item for item in files if item.get("filename", "").endswith(".whl")]
    candidates = [item for item in candidates if wheel_rank(item["filename"])]
    if not candidates:
        raise RuntimeError("no compatible wheel")
    return max(candidates, key=lambda item: wheel_rank(item["filename"]))


def download(package: str) -> Path:
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)
    info = data["info"]
    wheel = pick_wheel(data["urls"])
    target = CACHE / wheel["filename"]
    if not target.exists() or target.stat().st_size != wheel["size"]:
        print(f"downloading {package} {info['version']} -> {target.name}", flush=True)
        with urllib.request.urlopen(wheel["url"], timeout=180) as response:
            target.write_bytes(response.read())
    else:
        print(f"cached {target.name}", flush=True)
    return target


def unpack(wheel: Path) -> None:
    dist = wheel.name.split("-")[0]
    with zipfile.ZipFile(wheel) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = item.filename
            if ".data/" in name:
                prefix, _, rest = name.partition(".data/")
                area, _, rest = rest.partition("/")
                if area in ("purelib", "platlib"):
                    dest = SITE / rest
                elif area == "scripts":
                    dest = SCRIPTS / rest
                else:
                    dest = SITE / rest
            else:
                dest = SITE / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src:
                dest.write_bytes(src.read())
    print(f"unpacked {wheel.name}", flush=True)


def main() -> int:
    CACHE.mkdir(exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    failures = []
    for package in PACKAGES:
        try:
            unpack(download(package))
        except Exception as exc:
            failures.append(f"{package}: {exc}")
            print(f"FAILED {package}: {exc}", flush=True)
    if failures:
        print("\nFAILURES:\n" + "\n".join(failures))
        return 1
    print("\nAll wheels installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
