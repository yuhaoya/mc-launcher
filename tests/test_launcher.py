from __future__ import annotations

import os
import unittest
from pathlib import Path

from mclauncher.auth import offline_account
from mclauncher.errors import LauncherError
from mclauncher.launcher import LaunchOptions, build_command
from mclauncher.paths import Paths

from _helper import make_temp_dir, remove_temp_dir


def make_meta(demo_rule: bool = True) -> dict:
    game_args = [
        "--username",
        "${auth_player_name}",
        "--uuid",
        "${auth_uuid}",
        "--userType",
        "${user_type}",
    ]
    if demo_rule:
        game_args.append(
            {
                "rules": [{"action": "allow", "features": {"is_demo_user": True}}],
                "value": "--demo",
            }
        )
    return {
        "id": "1.0",
        "type": "release",
        "mainClass": "net.minecraft.client.main.Main",
        "assetIndex": {"id": "legacy"},
        "libraries": [
            {
                "name": "com.example:lib:1.0",
                "downloads": {
                    "artifact": {
                        "path": "com/example/lib/1.0/lib-1.0.jar",
                        "url": "https://example.invalid/lib.jar",
                    }
                },
            }
        ],
        "arguments": {
            "jvm": ["-Djava.library.path=${natives_directory}", "-cp", "${classpath}"],
            "game": game_args,
        },
    }


class TestBuildCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir()
        self.paths = Paths(self.root / "game", self.root / "config")
        self.meta = make_meta()
        lib = self.paths.library_path("com/example/lib/1.0/lib-1.0.jar")
        lib.parent.mkdir(parents=True)
        lib.write_bytes(b"jar")
        client = self.paths.client_jar("1.0")
        client.parent.mkdir(parents=True)
        client.write_bytes(b"client")
        self.account = offline_account("Steve")

    def tearDown(self) -> None:
        remove_temp_dir(self.root)

    def test_basic_command(self) -> None:
        options = LaunchOptions(version_id="1.0", account=self.account, memory_mb=2048)
        command, values = build_command(self.meta, self.paths, options, Path("java"))
        self.assertEqual(command[0], "java")
        self.assertIn("-Xmx2048M", command)
        self.assertIn("-Xms1024M", command)
        self.assertIn("net.minecraft.client.main.Main", command)
        self.assertIn("--username", command)
        self.assertEqual(command[command.index("--username") + 1], "Steve")
        self.assertIn(self.account.uuid_hex, command)
        self.assertIn("legacy", command)
        self.assertIn("--demo", command) if options.demo else self.assertNotIn("--demo", command)
        classpath = values["classpath"]
        self.assertIn(str(self.paths.client_jar("1.0")), classpath)
        self.assertIn(str(self.paths.library_path("com/example/lib/1.0/lib-1.0.jar")), classpath)
        self.assertEqual(classpath.count(os.pathsep), 1)

    def test_small_memory_uses_smaller_initial_heap(self) -> None:
        options = LaunchOptions(version_id="1.0", account=self.account, memory_mb=512)
        command, _ = build_command(self.meta, self.paths, options, Path("java"))
        self.assertIn("-Xms256M", command)
        self.assertIn("-Xmx512M", command)

    def test_demo_flag(self) -> None:
        options = LaunchOptions(version_id="1.0", account=self.account, demo=True)
        command, _ = build_command(self.meta, self.paths, options, Path("java"))
        self.assertIn("--demo", command)

    def test_custom_resolution_rule(self) -> None:
        self.meta["arguments"]["game"].append(
            {
                "rules": [{"action": "allow", "features": {"has_custom_resolution": True}}],
                "value": ["--width", "${resolution_width}", "--height", "${resolution_height}"],
            }
        )
        options = LaunchOptions(version_id="1.0", account=self.account, width=1280, height=720)
        command, _ = build_command(self.meta, self.paths, options, Path("java"))
        self.assertEqual(command[command.index("--width") + 1], "1280")
        self.assertEqual(command[command.index("--height") + 1], "720")

    def test_missing_client_raises(self) -> None:
        self.paths.client_jar("1.0").unlink()
        options = LaunchOptions(version_id="1.0", account=self.account)
        with self.assertRaises(LauncherError):
            build_command(self.meta, self.paths, options, Path("java"))

    def test_unknown_variable_raises(self) -> None:
        self.meta["arguments"]["game"].append("${unknown_variable}")
        options = LaunchOptions(version_id="1.0", account=self.account)
        with self.assertRaises(LauncherError):
            build_command(self.meta, self.paths, options, Path("java"))

    def test_legacy_minecraft_arguments(self) -> None:
        meta = dict(self.meta)
        meta.pop("arguments")
        meta["minecraftArguments"] = (
            "--username ${auth_player_name} --uuid ${auth_uuid} "
            "--gameDir ${game_directory} --assetsDir ${assets_root}"
        )
        options = LaunchOptions(version_id="1.0", account=self.account)
        command, _ = build_command(meta, self.paths, options, Path("java"))
        self.assertIn(str(self.paths.game_dir), command)
        self.assertIn(str(self.paths.assets), command)


if __name__ == "__main__":
    unittest.main()
