from __future__ import annotations

from contextlib import ExitStack
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SESSION_STORE = ROOT / "services" / "browser-service" / "app" / "session_store.py"
_spec = importlib.util.spec_from_file_location("geo_local_session_store", SESSION_STORE)
sessions = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sessions)


class LocalSessionPoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(sessions, "_SESSION_DIR", self.directory))
        self.stack.enter_context(patch.object(sessions, "_ACCOUNT_INDEX_PATH", self.directory / "accounts.json"))
        self.stack.enter_context(patch.object(sessions, "_POOL_URL", ""))
        self.stack.enter_context(patch.object(sessions, "_POOL_TOKEN", ""))
        sessions._last_checkout.local_by_engine = {}

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()
        sessions._last_checkout.local_by_engine = {}

    @staticmethod
    def state(value: str) -> dict:
        return {"cookies": [{"name": "account", "value": value}], "origins": []}

    def test_legacy_single_session_is_default_and_new_account_rotates(self):
        sessions.save_storage_state("doubao", self.state("legacy"))
        first = sessions.load_storage_state("doubao")
        self.assertEqual(first["cookies"][0]["value"], "legacy")
        sessions.report_session_outcome("doubao", result="success")

        account = sessions.create_local_account("doubao", "工作号")
        sessions.save_storage_state("doubao", self.state("second"), account["account_id"])
        second = sessions.load_storage_state("doubao")
        self.assertEqual(second["cookies"][0]["value"], "second")
        sessions.report_session_outcome("doubao", result="success")

        accounts = sessions.list_local_accounts("doubao")
        self.assertEqual({item["account_id"] for item in accounts}, {"default", "acct-001"})
        self.assertTrue(all(item["exists"] for item in accounts))

    def test_captcha_cools_account_and_next_checkout_uses_another(self):
        sessions.save_storage_state("qwen", self.state("one"))
        account = sessions.create_local_account("qwen", "账号二")
        sessions.save_storage_state("qwen", self.state("two"), account["account_id"])

        self.assertEqual(sessions.load_storage_state("qwen")["cookies"][0]["value"], "one")
        sessions.report_session_outcome("qwen", result="captcha")
        statuses = {item["account_id"]: item["status"] for item in sessions.list_local_accounts("qwen")}
        self.assertEqual(statuses["default"], "cooldown")

        self.assertEqual(sessions.load_storage_state("qwen")["cookies"][0]["value"], "two")
        sessions.report_session_outcome("qwen", result="success")

    def test_login_lost_account_is_removed_from_rotation(self):
        sessions.save_storage_state("wenxin", self.state("expired"))
        sessions.load_storage_state("wenxin")
        sessions.report_session_outcome("wenxin", result="login_lost")
        account = sessions.list_local_accounts("wenxin")[0]
        self.assertEqual(account["status"], "needs_login")
        self.assertEqual(sessions.get_local_account_count("wenxin"), 0)
        with self.assertRaisesRegex(RuntimeError, "冷却或需要重新登录"):
            sessions.load_storage_state("wenxin")

    def test_explicit_account_selection_does_not_checkout_another_account(self):
        sessions.save_storage_state("doubao", self.state("default"))
        account = sessions.create_local_account("doubao", "待检查账号")
        sessions.save_storage_state("doubao", self.state("pinned"), account["account_id"])

        with sessions.use_local_account("doubao", account["account_id"]):
            state = sessions.load_storage_state("doubao")
        self.assertEqual(state["cookies"][0]["value"], "pinned")
        self.assertEqual(sessions.get_last_local_account_id("doubao"), account["account_id"])

    def test_delete_account_preserves_legacy_default(self):
        sessions.save_storage_state("doubao", self.state("default"))
        account = sessions.create_local_account("doubao", "临时账号")
        sessions.save_storage_state("doubao", self.state("temporary"), account["account_id"])
        sessions.delete_local_account("doubao", account["account_id"])

        self.assertEqual(sessions.load_storage_state("doubao")["cookies"][0]["value"], "default")
        self.assertEqual([item["account_id"] for item in sessions.list_local_accounts("doubao")], ["default"])


if __name__ == "__main__":
    unittest.main()
