from __future__ import annotations

import platform
import re
from typing import Any, Mapping


def current_os() -> str:
    if platform.system() == "Windows":
        return "windows"
    if platform.system() == "Darwin":
        return "osx"
    return "linux"


def current_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("i386", "i486", "i586", "i686", "x86"):
        return "x86"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine


def current_os_version() -> str:
    return platform.version()


def build_context(features: Mapping[str, bool] | None = None) -> dict[str, Any]:
    return {
        "os": {
            "name": current_os(),
            "arch": current_arch(),
            "version": current_os_version(),
        },
        "features": dict(features or {}),
    }


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(text)))


def _match_version_range(actual: str, spec: Any) -> bool:
    """处理 1.21.9+ 版本 JSON 里的 os.versionRange。"""
    current = _version_tuple(actual)
    if isinstance(spec, dict):
        minimum = spec.get("min")
        maximum = spec.get("max")
        if minimum is not None and current < _version_tuple(minimum):
            return False
        if maximum is not None and current > _version_tuple(maximum):
            return False
        return True
    text = str(spec).strip()
    if not text:
        return True
    if text.startswith(("[", "(")) and "," in text:
        left_closed = text.startswith("[")
        right_closed = text.endswith("]")
        low, high = text[1:-1].split(",", 1)
        low, high = low.strip(), high.strip()
        if low and (current < _version_tuple(low) or (not left_closed and current == _version_tuple(low))):
            return False
        if high and (current > _version_tuple(high) or (not right_closed and current == _version_tuple(high))):
            return False
        return True
    return current == _version_tuple(text)


def _match_os(condition: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    actual = ctx["os"]
    if "name" in condition and condition["name"] != actual["name"]:
        return False
    if "arch" in condition and condition["arch"] != actual["arch"]:
        return False
    if "version" in condition:
        pattern = str(condition["version"])
        try:
            if not re.search(pattern, actual["version"]):
                return False
        except re.error:
            if pattern not in actual["version"]:
                return False
    if "versionRange" in condition and not _match_version_range(actual["version"], condition["versionRange"]):
        return False
    return True


def _match_features(condition: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    features = ctx.get("features", {})
    for key, expected in condition.items():
        actual = bool(features.get(key, False))
        if bool(expected) != actual:
            return False
    return True


def rule_matches(rule: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    if "os" in rule and not _match_os(rule["os"], ctx):
        return False
    if "features" in rule and not _match_features(rule["features"], ctx):
        return False
    return True


def is_allowed(rules: list[Mapping[str, Any]] | None, ctx: Mapping[str, Any]) -> bool:
    """按 Mojang 规则计算是否允许。

    没有 rules 时默认允许；有 rules 时以最后一条命中的规则为准。
    """
    if not rules:
        return True
    allowed = False
    for rule in rules:
        if rule_matches(rule, ctx):
            allowed = rule.get("action", "allow") == "allow"
    return allowed
