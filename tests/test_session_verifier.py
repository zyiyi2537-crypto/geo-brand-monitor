"""Regressions for guest inputs, account checks, and inconclusive login probes."""
from __future__ import annotations

import asyncio
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from tools.session_status import complete_session_results, session_label, session_ready


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "geo_session_verifier", ROOT / "services/browser-service/app/session_verifier.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def response(engine, payload=None, *, status=200, url=None):
    if url is None:
        host, path = verifier.ACCOUNT_ENDPOINTS[engine]
        url = f"https://{host}{path}/"
    return SimpleNamespace(url=url, status=status,
                           json=AsyncMock(return_value=payload))


class Page:
    def __init__(self, signals, responses=(), error=None):
        self.signals, self.responses, self.error = signals, responses, error
        self.listeners = {}

    def on(self, name, handler):
        self.listeners[name] = handler

    def remove_listener(self, name, handler):
        self.listeners.pop(name)

    async def goto(self, *args, **kwargs):
        if self.error:
            raise self.error
        for item in self.responses:
            self.listeners["response"](item)
        await asyncio.sleep(0)

    async def evaluate(self, script):
        return self.signals


class AccountChecks(unittest.TestCase):
    def test_only_non_guest_doubao_account_confirms_login(self):
        self.assertTrue(verifier.account_login_state("doubao", 200, {
            "data": {"is_visitor_account": False, "user_id": 123}}))
        self.assertFalse(verifier.account_login_state("doubao", 200, {
            "data": {"is_visitor_account": True, "user_id": 123}}))
        self.assertIsNone(verifier.account_login_state("doubao", 200, {
            "data": {"user_id": 123}}))

    def test_qwen_requires_successful_account_response(self):
        self.assertTrue(verifier.account_login_state("qwen", 200, {
            "success": True, "data": {"userId": "123"}}))
        self.assertIsNone(verifier.account_login_state("qwen", 200, {
            "success": False, "data": {"userId": "123"}}))
        self.assertIsNone(verifier.account_login_state("qwen", 502, {}))

    def test_endpoint_match_rejects_unrelated_auth_and_lookalike_domains(self):
        self.assertFalse(verifier.is_account_endpoint(
            "doubao", "https://www.doubao.com/web/auth/get_oauth_token/"))
        self.assertFalse(verifier.is_account_endpoint(
            "qwen", "https://api.qianwen.com.evil.test/growth/user/benefit/user/member/info"))

    def test_yuanbao_without_account_endpoint_ignores_network_responses(self):
        self.assertFalse(verifier.is_account_endpoint(
            "yuanbao", "https://yuanbao.tencent.com/api/user/info"))

    def test_ui_does_not_treat_inconclusive_results_as_expired_or_ready(self):
        self.assertEqual(session_label({"status": "timeout"}), "检测超时·请重试")
        self.assertEqual(session_label({"status": "error"}), "检测失败·请重试")
        self.assertFalse(session_ready({"status": "unavailable", "logged_in": True}))
        states = complete_session_results([{"engine": "doubao", "status": "ok",
                                            "logged_in": True}], ["doubao", "qwen"])
        self.assertTrue(session_ready(states["doubao"]))
        self.assertFalse(session_ready(states["qwen"]))


class BrowserChecks(unittest.IsolatedAsyncioTestCase):
    async def inspect(self, page, engine="qwen"):
        return await verifier.inspect_account_page(page, engine, "https://example.test/",
                                                   settle_timeout=0, guest_grace=0)

    async def test_qwen_guest_with_input_is_not_logged_in(self):
        page = Page({"input": True, "login": True})
        result = await self.inspect(page)
        self.assertEqual(result["status"], "expired")
        self.assertIs(result["logged_in"], False)
        self.assertEqual(page.listeners, {})

    async def test_input_without_account_or_login_signal_remains_unknown(self):
        result = await self.inspect(Page({"input": True, "login": False}))
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["logged_in"])

    async def test_doubao_new_contenteditable_and_confirmed_account_pass(self):
        page = Page({"input": True, "login": False}, [response("doubao", {
            "data": {"is_visitor_account": False, "user_id": 123}})])
        result = await self.inspect(page, "doubao")
        self.assertTrue(session_ready(result))

    async def test_yuanbao_enabled_composer_passes_with_unrelated_responses(self):
        page = Page({"input": True, "login": False}, [
            response("yuanbao", status=401, url="https://yuanbao.tencent.com/unrelated")])
        self.assertTrue(session_ready(await self.inspect(page, "yuanbao")))
        self.assertEqual(page.listeners, {})

    async def test_yuanbao_login_wall_does_not_pass_even_with_composer(self):
        result = await self.inspect(Page({"input": True, "login": True}), "yuanbao")
        self.assertEqual(result["status"], "expired")
        self.assertFalse(session_ready(result))

    async def test_qwen_account_success_passes_and_unrelated_401_is_ignored(self):
        page = Page({"input": True, "login": False}, [
            response("qwen", status=401, url="https://api.qianwen.com/unrelated/auth"),
            response("qwen", {"success": True, "data": {"userId": "123"}})])
        self.assertTrue(session_ready(await self.inspect(page)))

    async def test_account_outage_does_not_claim_login_expired(self):
        page = Page({"input": True, "login": True}, [response("qwen", status=502)])
        result = await self.inspect(page)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["logged_in"])

    async def test_authenticated_but_chat_not_ready_does_not_pass(self):
        page = Page({"input": False, "login": False}, [response("qwen", {
            "success": True, "data": {"userId": "123"}})])
        result = await self.inspect(page)
        self.assertEqual(result["status"], "unavailable")
        self.assertIs(result["logged_in"], True)
        self.assertFalse(session_ready(result))

    async def test_captcha_is_separate_from_login_expiry(self):
        result = await self.inspect(Page({"input": False, "challenge": True}))
        self.assertEqual(result["status"], "challenge")

    async def test_navigation_failure_closes_browser_without_claiming_logout(self):
        page = Page({}, error=TimeoutError("navigation failed"))
        adapter = SimpleNamespace(CHAT_URL="https://example.test/",
                                  _create_hot_page=AsyncMock(return_value=(page, object())),
                                  _close_hot_page=AsyncMock())
        result = await verifier.verify_account_session(adapter, "qwen")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["logged_in"])
        adapter._close_hot_page.assert_awaited_once()
        self.assertEqual(page.listeners, {})

    async def test_timeout_cancellation_also_closes_browser(self):
        adapter = SimpleNamespace(CHAT_URL="https://example.test/",
                                  _create_hot_page=AsyncMock(return_value=(object(), object())),
                                  _close_hot_page=AsyncMock())
        with patch.object(verifier, "inspect_account_page", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await verifier.verify_account_session(adapter, "qwen")
        adapter._close_hot_page.assert_awaited_once()


class GuiSessionCacheChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = SourceFileLoader("geo_gui_cache_test", str(ROOT / "geo_monitor_gui.pyw"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.gui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.gui)

    def test_session_file_change_invalidates_previous_success(self):
        with TemporaryDirectory() as temp, patch.object(self.gui, "SERVICE_DIR", Path(temp)):
            path = Path(temp) / "data/browser_sessions/qwen.json"
            path.parent.mkdir(parents=True)
            path.write_text("saved", encoding="utf-8")
            app = self.gui.GeoMonitorApp.__new__(self.gui.GeoMonitorApp)
            app.session_verified = {"qwen": "已确认登录"}
            app.session_verified_at = {"qwen": (self.gui.time.monotonic(), app._session_fingerprint("qwen"))}
            self.assertEqual(app._saved_session_label("qwen"), "已确认登录")
            path.write_text("changed_session", encoding="utf-8")
            self.assertEqual(app._saved_session_label("qwen"), "已保存·待检查")
            self.assertNotIn("qwen", app.session_verified)

    def test_old_success_expires_instead_of_showing_normal_forever(self):
        app = self.gui.GeoMonitorApp.__new__(self.gui.GeoMonitorApp)
        app.session_verified = {"qwen": "已确认登录"}
        app.session_verified_at = {"qwen": (0, (1, 2))}
        with patch.object(app, "_session_fingerprint", return_value=(1, 2)), \
                patch.object(self.gui.time, "monotonic", return_value=121):
            self.assertEqual(app._saved_session_label("qwen"), "已保存·待检查")


if __name__ == "__main__":
    unittest.main()
