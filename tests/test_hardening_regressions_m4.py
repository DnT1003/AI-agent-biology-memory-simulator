import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from core import utils


ROOT = Path(__file__).resolve().parents[1]


class AtomicLongPathRegressionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Win32 extended paths are Windows-specific")
    def test_atomic_json_supports_total_path_over_max_path(self):
        target = None
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            basename = ("long-state-" + ("x" * 190) + ".json")
            target = Path(directory) / basename
            self.assertGreater(len(os.path.abspath(target)), 260)

            try:
                utils.atomic_write_json(target, {"complete": True, "sequence": 7})
                self.assertEqual(
                    utils.atomic_read_json(target),
                    {"complete": True, "sequence": 7},
                )
            finally:
                # Remove the long file through the same explicit Win32
                # namespace so TemporaryDirectory only has a short root left.
                try:
                    os.unlink(utils._windows_extended_path(os.fspath(target)))
                except FileNotFoundError:
                    pass

    def test_short_paths_keep_their_existing_spelling(self):
        short_path = os.path.abspath(ROOT / "outputs" / "state.json")
        self.assertEqual(utils._windows_extended_path(short_path), short_path)

    @unittest.skipUnless(os.name == "nt", "Win32 extended paths are Windows-specific")
    def test_atomic_json_supports_a_deep_directory_over_max_path(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            deep_root = Path(directory) / ("d" * 120)
            deep_directory = deep_root / ("e" * 100)
            target = deep_directory / "state.json"
            self.assertGreater(len(os.path.abspath(deep_directory)), 260)

            try:
                utils.atomic_write_json(target, {"deep": True})
                self.assertEqual(utils.atomic_read_json(target), {"deep": True})
            finally:
                extended_root = utils._windows_extended_path(
                    os.fspath(deep_root),
                    force=True,
                )
                if os.path.exists(extended_root):
                    shutil.rmtree(extended_root)


class PackagingAndSecretRegressionTests(unittest.TestCase):
    def test_docker_context_excludes_local_non_runtime_artifacts(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for pattern in ("*.docx", "*.zip", "temp_backup/", "reports/", "*_REPORT.md"):
            self.assertRegex(dockerignore, rf"(?m)^{re.escape(pattern)}$")

    def test_journal_hmac_placeholder_is_empty_and_wired_to_both_writers(self):
        env_template = (ROOT / ".env.example").read_text(encoding="utf-8")
        secret_template = (ROOT / "k8s" / "aura-secrets.example.yaml").read_text(
            encoding="utf-8"
        )
        self.assertRegex(env_template, r"(?m)^AURA_EVENT_JOURNAL_HMAC_KEY=$")
        self.assertRegex(
            secret_template,
            r'(?m)^\s*AURA_EVENT_JOURNAL_HMAC_KEY:\s*""\s*$',
        )

        for manifest_name in ("brain-deployment.yaml", "dashboard-deployment.yaml"):
            manifest = (ROOT / "k8s" / manifest_name).read_text(encoding="utf-8")
            self.assertRegex(
                manifest,
                r"(?s)- name: AURA_EVENT_JOURNAL_HMAC_KEY\s+valueFrom:\s+"
                r"secretKeyRef:\s+name: aura-secrets\s+"
                r"key: AURA_EVENT_JOURNAL_HMAC_KEY",
            )

    def test_deploy_generates_and_preserves_a_distinct_journal_key_without_logging_it(self):
        script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")
        self.assertIn("$journalHmacKey = New-AuraAuthToken", script)
        self.assertIn(
            "AURA_EVENT_JOURNAL_HMAC_KEY = $journalHmacKey",
            script,
        )
        token_keys_block = script[
            script.index("$tokenKeys = @(") : script.index(
                "foreach ($tokenKey in $tokenKeys)"
            )
        ]
        self.assertIn('"AURA_EVENT_JOURNAL_HMAC_KEY"', token_keys_block)
        self.assertIn(
            'Invoke-CheckedSecretStdin kubectl @("create", "-f", "-")',
            script,
        )
        self.assertIn(
            'Invoke-CheckedSecretStdin kubectl @("replace", "-f", "-")',
            script,
        )
        self.assertNotIn("--from-literal", script)
        self.assertNotIn('"-p", $patchJson', script)

        creation_block = script[
            script.index("$dashboardToken = New-AuraAuthToken") : script.index(
                '"create aura-secrets"'
            )
        ]
        for variable in ("$dashboardToken", "$gpuToken", "$journalHmacKey"):
            self.assertEqual(
                creation_block.count(f"{variable} = New-AuraAuthToken"),
                1,
            )

        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith(
                ("Write-Host", "Write-Output", "Write-Warning", "Write-Error", "throw")
            ):
                self.assertNotIn("$journalHmacKey", stripped)
                self.assertNotIn("$newToken", stripped)


if __name__ == "__main__":
    unittest.main()
