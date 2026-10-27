from __future__ import annotations

import unittest

from mclauncher.auth import AuthError, offline_account, offline_uuid


class TestOfflineAccount(unittest.TestCase):
    def test_known_uuid(self) -> None:
        # 与 Java 的 UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(UTF_8)) 完全一致
        self.assertEqual(
            offline_uuid("Notch"),
            "b50ad385-829d-3141-a216-7e7d7539ba7f",
        )
        self.assertEqual(
            offline_uuid("Steve"),
            "5627dd98-e6be-3c21-b8a8-e92344183641",
        )

    def test_account_fields(self) -> None:
        account = offline_account("Steve")
        self.assertEqual(account.name, "Steve")
        self.assertEqual(account.user_type, "legacy")
        self.assertTrue(account.offline)
        self.assertEqual(account.uuid_hex, account.uuid.replace("-", ""))

    def test_invalid_names(self) -> None:
        with self.assertRaises(AuthError):
            offline_account("")
        with self.assertRaises(AuthError):
            offline_account("a" * 17)
        with self.assertRaises(AuthError):
            offline_account("bad name")


if __name__ == "__main__":
    unittest.main()
