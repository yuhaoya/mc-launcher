from __future__ import annotations

import re
from dataclasses import dataclass

_NAME_RE = re.compile(
    r"^(?P<group>[^:@]+):(?P<artifact>[^:@]+):(?P<version>[^:@]+)"
    r"(?::(?P<classifier>[^:@]+))?(?:@(?P<ext>[^:@]+))?$"
)


@dataclass(frozen=True)
class MavenName:
    group: str
    artifact: str
    version: str
    classifier: str | None = None
    ext: str = "jar"

    @property
    def path(self) -> str:
        parts = self.group.split(".") + [self.artifact, self.version]
        filename = f"{self.artifact}-{self.version}"
        if self.classifier:
            filename += f"-{self.classifier}"
        filename += f".{self.ext}"
        return "/".join(parts + [filename])


def parse(name: str) -> MavenName:
    match = _NAME_RE.match(name.strip())
    if not match:
        raise ValueError(f"无法解析 Maven 坐标: {name}")
    return MavenName(
        group=match.group("group"),
        artifact=match.group("artifact"),
        version=match.group("version"),
        classifier=match.group("classifier"),
        ext=match.group("ext") or "jar",
    )


def relative_path(name: str) -> str:
    return parse(name).path
