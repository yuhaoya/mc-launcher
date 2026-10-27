from __future__ import annotations

import unittest

from mclauncher.rules import build_context, is_allowed


class TestRules(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = build_context()
        self.os_name = self.ctx["os"]["name"]

    def test_no_rules_allows(self) -> None:
        self.assertTrue(is_allowed(None, self.ctx))
        self.assertTrue(is_allowed([], self.ctx))

    def test_allow_only_current_os(self) -> None:
        other = "linux" if self.os_name != "linux" else "windows"
        self.assertTrue(is_allowed([{"action": "allow", "os": {"name": self.os_name}}], self.ctx))
        self.assertFalse(is_allowed([{"action": "allow", "os": {"name": other}}], self.ctx))

    def test_last_matching_rule_wins(self) -> None:
        rules = [
            {"action": "allow", "os": {"name": self.os_name}},
            {"action": "disallow", "os": {"name": self.os_name}},
        ]
        self.assertFalse(is_allowed(rules, self.ctx))

    def test_feature_rules(self) -> None:
        rule = [{"action": "allow", "features": {"is_demo_user": True}}]
        self.assertFalse(is_allowed(rule, build_context({"is_demo_user": False})))
        self.assertTrue(is_allowed(rule, build_context({"is_demo_user": True})))

    def test_feature_false_rule(self) -> None:
        rule = [{"action": "allow", "features": {"has_custom_resolution": False}}]
        self.assertTrue(is_allowed(rule, build_context({})))
        self.assertFalse(is_allowed(rule, build_context({"has_custom_resolution": True})))


    def test_version_range(self) -> None:
        ctx = {
            "os": {"name": "windows", "arch": "x86_64", "version": "10.0.26100"},
            "features": {},
        }
        self.assertTrue(
            is_allowed([{"action": "allow", "os": {"versionRange": {"min": "10.0.17134"}}}], ctx)
        )
        self.assertFalse(
            is_allowed([{"action": "allow", "os": {"versionRange": {"max": "10.0.17134"}}}], ctx)
        )
        self.assertTrue(
            is_allowed([{"action": "allow", "os": {"versionRange": "[10.0,11.0)"}}], ctx)
        )
        self.assertFalse(
            is_allowed([{"action": "allow", "os": {"versionRange": "[9.0,10.0)"}}], ctx)
        )


if __name__ == "__main__":
    unittest.main()
