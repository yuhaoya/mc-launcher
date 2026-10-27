from __future__ import annotations

import unittest

from mclauncher.java import _major_from_runtime_version, _pick_runtime, java_platform_tag


def fake_manifest() -> dict:
    return {
        "windows-x64": {
            "jre-legacy": [
                {
                    "version": {"name": "8u51-cacert462b08", "released": "2025-10-06T13:49:59+00:00"},
                    "manifest": {"url": "https://example.invalid/legacy.json"},
                }
            ],
            "java-runtime-alpha": [
                {
                    "version": {"name": "16.0.1.9.1", "released": "2021-05-10T16:48:07+00:00"},
                    "manifest": {"url": "https://example.invalid/alpha.json"},
                }
            ],
            "java-runtime-gamma": [
                {
                    "version": {"name": "17.0.15", "released": "2025-05-19T08:28:47+00:00"},
                    "manifest": {"url": "https://example.invalid/gamma.json"},
                }
            ],
            "java-runtime-delta": [
                {
                    "version": {"name": "21.0.7", "released": "2025-05-19T08:34:42+00:00"},
                    "manifest": {"url": "https://example.invalid/delta.json"},
                }
            ],
        }
    }


class TestRuntimeSelection(unittest.TestCase):
    def test_major_parsing(self) -> None:
        self.assertEqual(_major_from_runtime_version("17.0.15", "java-runtime-gamma"), 17)
        self.assertEqual(_major_from_runtime_version("21.0.7", "java-runtime-delta"), 21)
        self.assertEqual(_major_from_runtime_version("8u51-cacert462b08", "jre-legacy"), 8)
        self.assertEqual(_major_from_runtime_version("1.8.0_51", "jre-legacy"), 8)

    def test_pick_by_component(self) -> None:
        comp, entry, major = _pick_runtime(fake_manifest(), "windows-x64", "java-runtime-gamma", 17)
        self.assertEqual(comp, "java-runtime-gamma")
        self.assertEqual(major, 17)
        self.assertTrue(entry["manifest"]["url"].endswith("gamma.json"))

    def test_pick_by_major(self) -> None:
        comp, _, major = _pick_runtime(fake_manifest(), "windows-x64", None, 21)
        self.assertEqual(comp, "java-runtime-delta")
        self.assertEqual(major, 21)

        comp, _, major = _pick_runtime(fake_manifest(), "windows-x64", None, 8)
        self.assertEqual(comp, "jre-legacy")

    def test_missing_major(self) -> None:
        with self.assertRaises(Exception):
            _pick_runtime(fake_manifest(), "windows-x64", None, 99)

    def test_platform_tag(self) -> None:
        self.assertIn(java_platform_tag(), {"windows-x64", "windows-x86", "windows-arm64", "linux", "linux-i386"})


if __name__ == "__main__":
    unittest.main()
