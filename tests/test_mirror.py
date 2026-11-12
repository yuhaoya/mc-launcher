from __future__ import annotations

import unittest
from pathlib import Path

from mclauncher.net import DownloadTask, apply_mirror_task, with_fallback

MIRROR_PAIRS = [
    ("https://libraries.minecraft.net", "https://bmclapi2.bangbang93.com/maven"),
    ("https://piston-meta.mojang.com", "https://bmclapi2.bangbang93.com"),
]


def bmclapi(url: str) -> str:
    for official, mirror in MIRROR_PAIRS:
        url = url.replace(official, mirror)
    return url


class TestMirrorFallback(unittest.TestCase):
    def test_mirror_keeps_official_as_fallback(self) -> None:
        task = DownloadTask(
            "https://libraries.minecraft.net/com/example/lib.jar",
            Path("lib.jar"),
            "a" * 40,
            123,
        )
        mirrored = apply_mirror_task(task, bmclapi)
        self.assertTrue(mirrored.url.startswith("https://bmclapi2.bangbang93.com/maven"))
        self.assertEqual(
            mirrored.fallbacks,
            ("https://libraries.minecraft.net/com/example/lib.jar",),
        )
        self.assertEqual(mirrored.sha1, task.sha1)
        self.assertEqual(mirrored.size, task.size)
        self.assertEqual(mirrored.dest, task.dest)

    def test_no_mirror_means_no_fallback(self) -> None:
        task = DownloadTask("https://example.invalid/a.jar", Path("a.jar"))
        untouched = apply_mirror_task(task, bmclapi)
        self.assertEqual(untouched.url, task.url)
        self.assertEqual(untouched.fallbacks, ())

    def test_applying_twice_does_not_duplicate(self) -> None:
        task = DownloadTask("https://libraries.minecraft.net/a.jar", Path("a.jar"))
        once = apply_mirror_task(task, bmclapi)
        twice = apply_mirror_task(once, bmclapi)
        self.assertEqual(twice.url, once.url)
        self.assertEqual(twice.fallbacks, once.fallbacks)

    def test_with_fallback_helper(self) -> None:
        primary, fallbacks = with_fallback("https://mirror/x", "https://official/x")
        self.assertEqual(primary, "https://mirror/x")
        self.assertEqual(fallbacks, ("https://official/x",))
        same_primary, same_fallbacks = with_fallback("https://official/x", "https://official/x")
        self.assertEqual(same_primary, "https://official/x")
        self.assertEqual(same_fallbacks, ())


if __name__ == "__main__":
    unittest.main()
