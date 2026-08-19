import json
import os
import threading
import unittest
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from core.settings_manager import SettingsManager
from core.utils import atomic_write_json
from dashboard import server as dashboard_server


class DashboardSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "settings.json"
        self.manager = object.__new__(SettingsManager)
        self.manager.settings_file = str(self.settings_path)
        self.manager.lock = threading.Lock()
        self.manager.settings = {
            "provider": "local",
            "local_model": "local-model",
            "gemini_model": "gemini-model",
            "openai_model": "openai-model",
            "anthropic_model": "anthropic-model",
            "system_prompt": "system",
            "gemini_api_key": "gemini-secret-sentinel",
            "openai_api_key": "openai-secret-sentinel",
            "anthropic_api_key": "anthropic-secret-sentinel",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_settings_file_and_public_view_never_contain_secrets(self):
        self.manager.save()
        serialized = self.settings_path.read_text(encoding="utf-8")
        public = self.manager.get_all()

        for secret_name in ("gemini_api_key", "openai_api_key", "anthropic_api_key"):
            self.assertNotIn(secret_name, serialized)
            self.assertNotIn(secret_name, public)
        self.assertNotIn("secret-sentinel", serialized)

    def test_legacy_file_secrets_and_unknown_keys_are_scrubbed(self):
        self.settings_path.write_text(
            json.dumps({
                "provider": "gemini",
                "gemini_api_key": "legacy-disk-secret",
                "unsupported_option": "legacy-value",
            }),
            encoding="utf-8",
        )
        self.manager.load()

        self.assertEqual(self.manager.get("provider"), "gemini")
        self.assertEqual(self.manager.get("gemini_api_key"), "gemini-secret-sentinel")
        self.assertNotIn("gemini_api_key", self.manager.get_all())
        persisted = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertNotIn("gemini_api_key", persisted)
        self.assertNotIn("unsupported_option", persisted)
        self.assertEqual(persisted["provider"], "gemini")

    def test_get_and_get_all_reload_external_file_changes(self):
        self.manager.save()
        initial_mtime = os.stat(self.settings_path).st_mtime_ns

        external = self.manager.get_all()
        external["provider"] = "anthropic"
        atomic_write_json(str(self.settings_path), external)
        first_mtime = initial_mtime + 1_000_000_000
        os.utime(self.settings_path, ns=(first_mtime, first_mtime))

        self.assertEqual(self.manager.get("provider"), "anthropic")

        external["provider"] = "openai"
        external["system_prompt"] = "externally updated"
        atomic_write_json(str(self.settings_path), external)
        second_mtime = first_mtime + 1_000_000_000
        os.utime(self.settings_path, ns=(second_mtime, second_mtime))

        reloaded = self.manager.get_all()
        self.assertEqual(reloaded["provider"], "openai")
        self.assertEqual(reloaded["system_prompt"], "externally updated")

    def test_secret_updates_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.update_all({"gemini_api_key": "attacker-value"})
        self.assertEqual(self.manager.get("gemini_api_key"), "gemini-secret-sentinel")

    def test_http_api_is_public_only_and_has_no_wildcard_cors(self):
        with patch.object(dashboard_server, "settings_manager", self.manager):
            client = TestClient(dashboard_server.app)
            root_response = client.get("/")
            self.assertEqual(root_response.status_code, 200)
            self.assertIn("<!DOCTYPE html>", root_response.text)

            response = client.get("/api/settings", headers={"Origin": "https://attacker.invalid"})

            self.assertEqual(response.status_code, 200)
            self.assertNotIn("access-control-allow-origin", response.headers)
            self.assertNotIn("api_key", response.text)
            self.assertNotIn("secret-sentinel", response.text)

            rejected = client.post(
                "/api/settings",
                json={"gemini_api_key": "submitted-secret-sentinel"},
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertNotIn("submitted-secret-sentinel", rejected.text)

            accepted = client.post("/api/settings", json={"provider": "gemini"})
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()["settings"]["provider"], "gemini")
            self.assertNotIn("api_key", accepted.text)


if __name__ == "__main__":
    unittest.main()
