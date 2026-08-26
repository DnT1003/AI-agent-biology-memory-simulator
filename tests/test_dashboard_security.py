import json
import os
import secrets
import threading
import unittest
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from config import Config, _optional_dashboard_auth_token
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

    def test_config_token_parser_and_validation(self):
        # Valid base64url / token68 strings of length 32..256
        valid_32 = "a" * 32
        valid_256 = "b" * 256
        valid_urlsafe = secrets.token_urlsafe(32)
        valid_hex = secrets.token_hex(32)
        valid_mixed = "Abc-123_.~+/=xyz9876543210123456789"

        self.assertEqual(_optional_dashboard_auth_token(valid_32), valid_32)
        self.assertEqual(_optional_dashboard_auth_token(valid_256), valid_256)
        self.assertEqual(_optional_dashboard_auth_token(valid_urlsafe), valid_urlsafe)
        self.assertEqual(_optional_dashboard_auth_token(valid_hex), valid_hex)
        self.assertEqual(_optional_dashboard_auth_token(valid_mixed), valid_mixed)

        # Invalid lengths
        self.assertIsNone(_optional_dashboard_auth_token(""))
        self.assertIsNone(_optional_dashboard_auth_token("a" * 31))
        self.assertIsNone(_optional_dashboard_auth_token("a" * 257))

        # Non-string inputs
        self.assertIsNone(_optional_dashboard_auth_token(None))
        self.assertIsNone(_optional_dashboard_auth_token(12345678901234567890123456789012))
        self.assertIsNone(_optional_dashboard_auth_token(True))
        self.assertIsNone(_optional_dashboard_auth_token(False))
        self.assertIsNone(_optional_dashboard_auth_token(["a" * 32]))
        self.assertIsNone(_optional_dashboard_auth_token({"token": "a" * 32}))

        # Whitespace and control characters
        self.assertIsNone(_optional_dashboard_auth_token(" " + ("a" * 32)))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 32) + " "))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 16) + " " + ("a" * 15)))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 32) + "\n"))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 32) + "\r"))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 32) + "\t"))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 31) + "\x00"))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 31) + "\x1f"))
        self.assertIsNone(_optional_dashboard_auth_token(("a" * 31) + "\x7f"))

        # Non-ASCII and disallowed symbols
        self.assertIsNone(_optional_dashboard_auth_token("token_with_unicode_\u00e9_" + ("a" * 20)))
        self.assertIsNone(_optional_dashboard_auth_token("token_with_zero_width\u200b_" + ("a" * 20)))
        self.assertIsNone(_optional_dashboard_auth_token("<script>alert(1)</script>" + ("a" * 20)))
        self.assertIsNone(_optional_dashboard_auth_token('token"with"quotes' + ("a" * 20)))
        self.assertIsNone(_optional_dashboard_auth_token("token;with;semicolon" + ("a" * 20)))

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
        token = "a" * 32
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", token), patch.object(
            dashboard_server, "settings_manager", self.manager
        ):
            client = TestClient(
                dashboard_server.app,
                headers={"Authorization": f"Bearer {token}"},
            )
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

    def test_root_is_public_and_does_not_require_auth(self):
        for token_config in [None, "t" * 32]:
            with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", token_config):
                client = TestClient(dashboard_server.app)
                res = client.get("/")
                self.assertEqual(res.status_code, 200)
                self.assertIn("<!DOCTYPE html>", res.text)
                self.assertIn("Aura Cognitive Dashboard", res.text)

    def test_missing_server_token_config_returns_503_generic(self):
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", None), patch.object(
            dashboard_server, "settings_manager", self.manager
        ):
            client = TestClient(dashboard_server.app)
            r_state = client.get("/api/state")
            self.assertEqual(r_state.status_code, 503)
            self.assertEqual(r_state.json(), {"detail": "Dashboard authentication unavailable"})

            r_settings = client.get("/api/settings")
            self.assertEqual(r_settings.status_code, 503)

            r_check = client.get("/api/auth/check")
            self.assertEqual(r_check.status_code, 503)

            r_chat = client.post("/api/chat", json={"message": "hello"})
            self.assertEqual(r_chat.status_code, 503)

            r_post_settings = client.post("/api/settings", json={"provider": "local"})
            self.assertEqual(r_post_settings.status_code, 503)

    def test_missing_wrong_or_malformed_auth_header_returns_401_with_www_authenticate(self):
        server_token = "s" * 32
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", server_token):
            client = TestClient(dashboard_server.app)

            # Missing Authorization header
            r_missing = client.get("/api/auth/check")
            self.assertEqual(r_missing.status_code, 401)
            self.assertEqual(r_missing.headers.get("www-authenticate"), "Bearer")

            # Wrong token
            r_wrong = client.get(
                "/api/auth/check",
                headers={"Authorization": f"Bearer {'w' * 32}"},
            )
            self.assertEqual(r_wrong.status_code, 401)
            self.assertEqual(r_wrong.headers.get("www-authenticate"), "Bearer")

            # Malformed scheme: Basic
            r_basic = client.get(
                "/api/auth/check",
                headers={"Authorization": f"Basic {server_token}"},
            )
            self.assertEqual(r_basic.status_code, 401)
            self.assertEqual(r_basic.headers.get("www-authenticate"), "Bearer")

            # Malformed format: no space/token
            r_no_token = client.get(
                "/api/auth/check",
                headers={"Authorization": "Bearer"},
            )
            self.assertEqual(r_no_token.status_code, 401)
            self.assertEqual(r_no_token.headers.get("www-authenticate"), "Bearer")

            # Malformed format: empty token
            r_empty_token = client.get(
                "/api/auth/check",
                headers={"Authorization": "Bearer "},
            )
            self.assertEqual(r_empty_token.status_code, 401)
            self.assertEqual(r_empty_token.headers.get("www-authenticate"), "Bearer")

            # Malformed format: extra tokens
            r_extra = client.get(
                "/api/auth/check",
                headers={"Authorization": f"Bearer {server_token} extra_data"},
            )
            self.assertEqual(r_extra.status_code, 401)
            self.assertEqual(r_extra.headers.get("www-authenticate"), "Bearer")

            # Malformed format: oversized header (> 512 bytes)
            r_oversized = client.get(
                "/api/auth/check",
                headers={"Authorization": "Bearer " + ("x" * 600)},
            )
            self.assertEqual(r_oversized.status_code, 401)
            self.assertEqual(r_oversized.headers.get("www-authenticate"), "Bearer")

    def test_valid_auth_token_passes_auth_and_check_endpoint(self):
        valid_token = "valid-token-service-" + "v" * 32
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", valid_token), patch.object(
            dashboard_server, "settings_manager", self.manager
        ):
            client = TestClient(
                dashboard_server.app,
                headers={"Authorization": f"Bearer {valid_token}"},
            )
            r_check = client.get("/api/auth/check")
            self.assertEqual(r_check.status_code, 200)
            self.assertEqual(r_check.json(), {"authenticated": True})

            r_settings = client.get("/api/settings")
            self.assertEqual(r_settings.status_code, 200)
            self.assertEqual(r_settings.json()["provider"], "local")

    def test_unauthorized_post_never_writes_spool_and_never_mutates_settings(self):
        server_token = "valid-server-token-" + "v" * 32
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", server_token), patch.object(
            dashboard_server, "settings_manager", self.manager
        ):
            client = TestClient(dashboard_server.app)

            # Unauthorized POST /api/settings
            r_settings = client.post(
                "/api/settings",
                json={"provider": "gemini"},
                headers={"Authorization": "Bearer wrong-token-unauthorized-32chars"},
            )
            self.assertEqual(r_settings.status_code, 401)
            self.assertEqual(self.manager.get("provider"), "local")

            # Unauthorized POST /api/chat
            mock_requests = Mock()
            with patch.object(
                dashboard_server,
                "_get_chat_spools",
                return_value=(mock_requests, Mock()),
            ):
                r_chat = client.post(
                    "/api/chat",
                    json={"message": "unauthorized chat message"},
                )
                self.assertEqual(r_chat.status_code, 401)
                mock_requests.enqueue_request.assert_not_called()

    def test_auth_responses_never_leak_tokens(self):
        server_token = "server-secret-sentinel-" + "s" * 32
        client_sentinel = "client-submitted-sentinel-" + "c" * 32

        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", server_token):
            client = TestClient(dashboard_server.app)

            # Unauthenticated request
            r_unauth = client.get("/api/auth/check")
            self.assertEqual(r_unauth.status_code, 401)
            self.assertNotIn("server-secret-sentinel", r_unauth.text)
            self.assertNotIn("server-secret-sentinel", str(r_unauth.headers))

            # Wrong token request
            r_wrong = client.get(
                "/api/auth/check",
                headers={"Authorization": f"Bearer {client_sentinel}"},
            )
            self.assertEqual(r_wrong.status_code, 401)
            self.assertNotIn("server-secret-sentinel", r_wrong.text)
            self.assertNotIn("client-submitted-sentinel", r_wrong.text)
            self.assertNotIn("server-secret-sentinel", str(r_wrong.headers))
            self.assertNotIn("client-submitted-sentinel", str(r_wrong.headers))

    def test_env_example_placeholder_is_empty_and_fails_validation(self):
        env_example_path = dashboard_server.PROJECT_ROOT / ".env.example"
        self.assertTrue(env_example_path.exists())
        content = env_example_path.read_text(encoding="utf-8")

        token_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip().startswith("AURA_DASHBOARD_AUTH_TOKEN=")
        ]
        self.assertEqual(len(token_lines), 1)
        token_val = token_lines[0].split("=", 1)[1].strip()
        self.assertEqual(token_val, "")
        self.assertIsNone(_optional_dashboard_auth_token(token_val))

    def test_live_endpoint_is_public_and_returns_alive(self):
        for token_config in [None, "t" * 32]:
            with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", token_config):
                client = TestClient(dashboard_server.app)
                res = client.get("/live")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json(), {"status": "alive"})

    def test_ready_endpoint_is_public_and_gated_by_token_configuration(self):
        # When token is configured
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", "t" * 32):
            client = TestClient(dashboard_server.app)
            res = client.get("/ready")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"status": "ready"})

        # When token is missing/unconfigured
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", None):
            client = TestClient(dashboard_server.app)
            res = client.get("/ready")
            self.assertEqual(res.status_code, 503)
            self.assertEqual(res.json().get("status"), "not_ready")

    def test_bearer_scheme_comparison_is_case_insensitive(self):
        server_token = "valid-token-service-" + "v" * 32
        with patch.object(dashboard_server.Config, "DASHBOARD_AUTH_TOKEN", server_token):
            client = TestClient(dashboard_server.app)
            for scheme in ["Bearer", "bearer", "BEARER", "bEaReR"]:
                res = client.get(
                    "/api/auth/check",
                    headers={"Authorization": f"{scheme} {server_token}"},
                )
                self.assertEqual(res.status_code, 200, f"Failed for scheme: {scheme}")
                self.assertEqual(res.json(), {"authenticated": True})

    def test_dashboard_ui_script_and_storage_contract(self):
        html = dashboard_server.DASHBOARD_FILE.read_text(encoding="utf-8")

        # Wrapper function exists and attaches Authorization header
        self.assertIn("async function apiFetch(url, options = {})", html)
        self.assertIn("headers.set('Authorization', 'Bearer ' + token);", html)
        self.assertIn("if (response.status === 401)", html)
        self.assertIn("clearAuthToken();", html)
        self.assertIn("updateAuthUI(false);", html)

        # No raw fetch calls to /api/ in the HTML script
        self.assertNotIn("fetch('/api", html)
        self.assertNotIn("fetch(`/api", html)

        # Storage contract: sessionStorage is used, localStorage is NEVER used
        self.assertIn("sessionStorage.getItem(AUTH_STORAGE_KEY)", html)
        self.assertIn("sessionStorage.setItem(AUTH_STORAGE_KEY", html)
        self.assertIn("sessionStorage.removeItem(AUTH_STORAGE_KEY)", html)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("document.cookie", html)

        # No server token embedded in HTML
        self.assertNotIn("AURA_DASHBOARD_AUTH_TOKEN", html)

        # Unlock / Lock controls exist in the DOM
        self.assertIn('id="auth-locked-view"', html)
        self.assertIn('id="auth-unlocked-view"', html)
        self.assertIn('id="auth-token-input"', html)
        self.assertIn("unlockDashboard", html)
        self.assertIn("lockDashboard", html)

        # M4.1a contracts: content-area hidden by default
        self.assertIn('id="content-area" style="display: none;"', html)

        # M4.1a contracts: lockDashboard reloads page to clear rendered data
        self.assertIn("window.location.reload()", html)

        # M4.1a contracts: auth generation counter
        self.assertIn("let authGeneration = 0;", html)
        self.assertIn("authGeneration++", html)
        self.assertIn("currentGen === authGeneration", html)

        # M4.1a contracts: apiFetch returns null and does not call fetch when no token
        self.assertIn("if (!token) {", html)
        self.assertIn("return null;", html)

        # M4.1a contracts: initDashboard awaits checkInitialAuth before fetching data
        self.assertIn("async function initDashboard()", html)
        self.assertIn("const isAuthenticated = await checkInitialAuth();", html)


if __name__ == "__main__":
    unittest.main()
