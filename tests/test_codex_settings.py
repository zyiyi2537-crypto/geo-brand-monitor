"""Read selected local credentials without leaking or changing them."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.codex_settings import load_codex_settings


CONFIG = '''model = "my-model"
model_provider = "custom"
[model_providers.custom]
base_url = "https://provider.example/api/v2"
wire_api = "responses"
'''


class CodexSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex = self.root / "codex"
        self.codex.mkdir()
        self.cc = self.root / "cc-switch"
        self.cc.mkdir()

    def load(self, env=None):
        return load_codex_settings(codex_dir=self.codex, cc_switch_dir=self.cc, environ=env or {})

    def save_cc(self, config=CONFIG):
        with closing(sqlite3.connect(self.cc / "cc-switch.db")) as conn, conn:
            conn.execute("CREATE TABLE providers (id TEXT, app_type TEXT, settings_config TEXT, is_current INTEGER)")
            for app, current, key in (("codex", 1, "current-key"), ("codex", 0, "other-key"), ("claude", 1, "claude-key")):
                conn.execute("INSERT INTO providers VALUES (?, ?, ?, ?)",
                             (key, app, json.dumps({"config": config, "auth": {"OPENAI_API_KEY": key}}), current))

    def test_live_inline_key_and_protocol_take_precedence(self):
        config = CONFIG + 'experimental_bearer_token = "live-key"\n'
        path = self.codex / "config.toml"
        path.write_text(config, encoding="utf-8")
        self.save_cc()
        settings = self.load()
        self.assertEqual(settings.api_key, "live-key")
        self.assertEqual(settings.wire_api, "responses")
        self.assertNotIn("live-key", repr(settings))
        self.assertEqual(path.read_text(encoding="utf-8"), config)

    def test_auth_file_and_provider_env_key(self):
        path = self.codex / "config.toml"
        path.write_text(CONFIG, encoding="utf-8")
        (self.codex / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "file-key"}), encoding="utf-8")
        self.assertEqual(self.load().api_key, "file-key")
        path.write_text(CONFIG + 'env_key = "PROVIDER_API_KEY"\n', encoding="utf-8")
        self.assertEqual(self.load({"PROVIDER_API_KEY": "env-key"}).api_key, "env-key")
        with self.assertRaisesRegex(ValueError, "环境变量"):
            self.load()

    def test_cc_switch_fallback_only_uses_current_codex_provider(self):
        self.save_cc()
        settings = self.load()
        self.assertEqual(settings.api_key, "current-key")
        self.assertEqual(settings.base_url, "https://provider.example/api/v2")

    def test_matching_live_config_can_use_cc_switch_key(self):
        (self.codex / "config.toml").write_text(CONFIG, encoding="utf-8")
        self.save_cc()
        self.assertEqual(self.load().api_key, "current-key")

    def test_never_borrows_key_from_a_different_live_provider(self):
        (self.codex / "config.toml").write_text(CONFIG.replace("provider.example", "different.example"), encoding="utf-8")
        self.save_cc()
        with self.assertRaisesRegex(ValueError, "API Key"):
            self.load()

    def test_refresh_reads_new_config_and_rejects_oauth_only(self):
        path = self.codex / "config.toml"
        path.write_text(CONFIG + 'experimental_bearer_token = "first-key"\n', encoding="utf-8")
        self.assertEqual(self.load().api_key, "first-key")
        path.write_text(CONFIG.replace("my-model", "new-model") + 'experimental_bearer_token = "second-key"\n', encoding="utf-8")
        settings = self.load()
        self.assertEqual((settings.model, settings.api_key), ("new-model", "second-key"))
        path.write_text(CONFIG, encoding="utf-8")
        (self.codex / "auth.json").write_text(json.dumps({"tokens": {"access_token": "oauth-token"}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ChatGPT"):
            self.load()

    def test_codex_home_override(self):
        (self.codex / "config.toml").write_text(CONFIG + 'experimental_bearer_token = "home-key"\n', encoding="utf-8")
        settings = load_codex_settings(cc_switch_dir=self.cc, environ={"CODEX_HOME": str(self.codex)})
        self.assertEqual(settings.api_key, "home-key")


if __name__ == "__main__":
    unittest.main()
