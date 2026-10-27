from __future__ import annotations

import unittest

from mclauncher import maven


class TestMaven(unittest.TestCase):
    def test_plain(self) -> None:
        parsed = maven.parse("com.google.guava:guava:32.1.2-jre")
        self.assertEqual(parsed.group, "com.google.guava")
        self.assertEqual(parsed.artifact, "guava")
        self.assertEqual(parsed.version, "32.1.2-jre")
        self.assertEqual(parsed.path, "com/google/guava/guava/32.1.2-jre/guava-32.1.2-jre.jar")

    def test_classifier(self) -> None:
        parsed = maven.parse("org.lwjgl:lwjgl:3.3.1:natives-windows")
        self.assertEqual(parsed.classifier, "natives-windows")
        self.assertEqual(
            parsed.path,
            "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar",
        )

    def test_extension(self) -> None:
        parsed = maven.parse("net.java:jinput:2.0.5@zip")
        self.assertEqual(parsed.ext, "zip")
        self.assertTrue(parsed.path.endswith("jinput-2.0.5.zip"))

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            maven.parse("not-a-coordinate")


if __name__ == "__main__":
    unittest.main()
