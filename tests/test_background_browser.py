"""Regression checks for service/login desktop separation and old services."""
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tools.background_browser import background_service_ready, service_environment

ROOT = Path(__file__).resolve().parents[1]


class BackgroundBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = SourceFileLoader("background_gui_test", str(ROOT / "geo_monitor_gui.pyw"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.gui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.gui)

    def app(self):
        app = self.gui.GeoMonitorApp.__new__(self.gui.GeoMonitorApp)
        app.events = queue.Queue()
        app.service_lock = threading.Lock()
        app.service_process = None
        app.browser_desktop = None
        app.browser_port = 8093
        app.browser_url = "http://127.0.0.1:8093"
        app.closing = False
        return app

    def response(self, payload):
        reply = io.BytesIO(json.dumps(payload).encode())
        reply.status = 200
        return reply

    def test_service_flags_do_not_change_the_login_environment(self):
        app = self.app()
        with patch.dict(os.environ, {"GEO_BROWSER_BACKGROUND": "1", "GEO_BROWSER_PRIVATE_DESKTOP": "1"}):
            login = app._env()
        service = service_environment(login, isolated=True)
        self.assertNotIn("GEO_BROWSER_BACKGROUND", login)
        self.assertNotIn("GEO_BROWSER_PRIVATE_DESKTOP", login)
        self.assertEqual(service["GEO_BROWSER_BACKGROUND"], "1")
        self.assertEqual(service["GEO_BROWSER_PRIVATE_DESKTOP"], "1")
        self.assertEqual(service["BROWSER_SESSION_DIR"], login["BROWSER_SESSION_DIR"])

    def test_old_services_and_nonisolated_windows_services_are_rejected(self):
        self.assertFalse(background_service_ready({"status": "healthy"}))
        if os.name == "nt":
            self.assertFalse(background_service_ready({"background_mode": True}))
        self.assertTrue(background_service_ready({"background_mode": True, "desktop_isolated": True}))

    def test_occupied_legacy_port_starts_isolated_service_on_new_port(self):
        app = self.app()
        desktop = Mock(handle=123)
        process = Mock()
        process.poll.return_value = None
        desktop.launch.return_value = process
        probe = Mock()
        probe.getsockname.return_value = ("127.0.0.1", 49123)
        probe_context = Mock()
        probe_context.__enter__ = Mock(return_value=probe)
        probe_context.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(self.gui, "REPORTS", Path(temp)), \
                patch.object(self.gui, "PYTHON", Path(__file__)), \
                patch.object(self.gui, "urlopen", side_effect=[
                    self.response({"status": "healthy"}),
                    self.response({"background_mode": True, "desktop_isolated": True}),
                ]), \
                patch.object(self.gui.socket, "socket", return_value=probe_context), \
                patch.object(self.gui, "BrowserDesktop", return_value=desktop), \
                patch.object(self.gui.time, "sleep"):
            self.assertTrue(app._ensure_service())
        self.assertEqual(app.browser_url, "http://127.0.0.1:49123")
        self.assertIn("49123", desktop.launch.call_args.args[0])
        self.assertEqual(desktop.launch.call_args.kwargs["env"]["GEO_BROWSER_BACKGROUND"], "1")
        self.assertEqual(desktop.launch.call_args.kwargs["env"]["GEO_BROWSER_PRIVATE_DESKTOP"], "1")

    def test_background_start_failure_does_not_launch_visible_fallback(self):
        app = self.app()
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(self.gui, "REPORTS", Path(temp)), \
                patch.object(self.gui, "PYTHON", Path(__file__)), \
                patch.object(self.gui, "urlopen", side_effect=OSError("not running")), \
                patch.object(self.gui, "BrowserDesktop", side_effect=OSError("desktop unavailable")), \
                patch.object(self.gui.subprocess, "Popen") as launch:
            self.assertFalse(app._ensure_service())
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
