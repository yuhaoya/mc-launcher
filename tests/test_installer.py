from __future__ import annotations

import io
import struct
import unittest
import zipfile
from pathlib import Path

from mclauncher.installer import Installer, build_library_plan
from mclauncher.paths import Paths
from mclauncher.rules import build_context

from _helper import make_temp_dir, remove_temp_dir


class TestLibraryPlan(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir()
        self.paths = Paths(self.root / "game", self.root / "config")

    def tearDown(self) -> None:
        remove_temp_dir(self.root)

    def test_plan_collects_artifact_and_natives(self) -> None:
        meta = {
            "libraries": [
                {
                    "name": "com.example:lib:1.0",
                    "downloads": {
                        "artifact": {
                            "path": "com/example/lib/1.0/lib-1.0.jar",
                            "url": "https://example.invalid/lib.jar",
                            "sha1": "a" * 40,
                            "size": 10,
                        }
                    },
                },
                {
                    "name": "org.lwjgl:lwjgl:3.3.1",
                    "natives": {"windows": "natives-windows-${arch}"},
                    "downloads": {
                        "classifiers": {
                            "natives-windows-64": {
                                "path": "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows-64.jar",
                                "url": "https://example.invalid/natives.jar",
                                "sha1": "b" * 40,
                                "size": 20,
                            }
                        }
                    },
                },
            ]
        }
        plan = build_library_plan(meta, self.paths, build_context())
        self.assertEqual(len(plan.classpath), 1)
        if struct.calcsize("P") * 8 == 64:
            self.assertEqual(len(plan.native_jars), 1)
            self.assertEqual(len(plan.tasks), 2)
            self.assertIn("natives-windows-64", str(plan.native_jars[0][0]))


class TestNativesExtraction(unittest.TestCase):
    def test_extract_and_exclude_meta_inf(self) -> None:
        root = make_temp_dir()
        try:
            paths = Paths(root / "game", root / "config")
            jar = paths.library_path("org/example/native/1.0/native-1.0-natives-windows.jar")
            jar.parent.mkdir(parents=True)
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("test.dll", b"binary")
                archive.writestr("META-INF/MANIFEST.MF", b"manifest")
                archive.writestr("sub/other.dll", b"other")
            installer = Installer(paths, stream=io.StringIO())
            installer._extract_natives("1.0", [(jar, ["META-INF/"])])
            natives = paths.natives_dir("1.0")
            self.assertTrue((natives / "test.dll").is_file())
            self.assertTrue((natives / "sub" / "other.dll").is_file())
            self.assertFalse((natives / "META-INF" / "MANIFEST.MF").exists())
        finally:
            remove_temp_dir(root)


class TestLogConfig(unittest.TestCase):
    def test_pattern_log_is_generated(self) -> None:
        root = make_temp_dir()
        try:
            source = root / "client-1.2.3.xml"
            source.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Configuration><Appenders><Console name="SysOut">'
                "<LegacyXMLLayout /></Console></Appenders></Configuration>\n",
                encoding="utf-8",
            )
            Installer._ensure_pattern_log(source)
            target = root / "client-1.2.3.mcl.xml"
            self.assertTrue(target.is_file())
            text = target.read_text(encoding="utf-8")
            self.assertIn("PatternLayout", text)
            self.assertNotIn("LegacyXMLLayout", text)
            self.assertIn("LegacyXMLLayout", source.read_text(encoding="utf-8"))
        finally:
            remove_temp_dir(root)


if __name__ == "__main__":
    unittest.main()
