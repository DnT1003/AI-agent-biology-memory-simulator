import re
import shlex
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTests(unittest.TestCase):
    def test_dashboard_docker_copy_sources_exist(self):
        dockerfile = (ROOT / "Dockerfile.dashboard").read_text(encoding="utf-8")
        for raw_line in dockerfile.splitlines():
            if not raw_line.startswith("COPY "):
                continue
            tokens = shlex.split(raw_line, posix=True)
            for source in tokens[1:-1]:
                self.assertTrue((ROOT / source.rstrip("/")).exists(), source)

        self.assertIn('"dashboard.server:app"', dockerfile)
        self.assertIn('"8050"', dockerfile)

    def test_local_chroma_image_has_a_matching_build_step(self):
        manifest = (ROOT / "k8s" / "chroma-deployment.yaml").read_text(encoding="utf-8")
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        self.assertIn("image: aura/chromadb:latest", manifest)
        self.assertIn("imagePullPolicy: Never", manifest)
        self.assertRegex(
            deploy_script,
            r'Invoke-CheckedNative\s+docker\s+@\(\s*"build",\s*"-f",\s*'
            r'"Dockerfile\.chroma",\s*"-t",\s*"aura/chromadb:latest",\s*"\."\s*\)',
        )

    def test_persistent_volumes_are_cluster_scoped_and_claims_are_pinned(self):
        storage = (ROOT / "k8s" / "storage-pvc.yaml").read_text(encoding="utf-8")
        documents = [document for document in re.split(r"(?m)^---\s*$", storage) if document.strip()]
        expected_bindings = {
            "brain-pvc": "brain-pv",
            "chroma-pvc": "chroma-pv",
            "gemma-pvc": "gemma-pv",
            "gpu-pvc": "gpu-pv",
        }

        for document in documents:
            if re.search(r"(?m)^kind:\s+PersistentVolume$", document):
                self.assertNotRegex(document, r"(?m)^\s+namespace:")

        for claim, volume in expected_bindings.items():
            claim_document = next(document for document in documents if f"name: {claim}" in document)
            self.assertIn(f"volumeName: {volume}", claim_document)

    def test_dashboard_ports_and_probes_match_runtime_contract(self):
        dashboard = (ROOT / "k8s" / "dashboard-deployment.yaml").read_text(encoding="utf-8")

        self.assertIn("containerPort: 8050", dashboard)
        self.assertEqual(dashboard.count("port: 8050"), 2)
        self.assertIn("targetPort: 8050", dashboard)
        self.assertRegex(
            dashboard,
            r"(?s)livenessProbe:\s*\n\s*httpGet:\s*\n\s*path:\s*/live\s*\n\s*port:\s*8050",
        )
        self.assertRegex(
            dashboard,
            r"(?s)readinessProbe:\s*\n\s*httpGet:\s*\n\s*path:\s*/ready\s*\n\s*port:\s*8050",
        )

    def test_dashboard_deployment_receives_required_auth_secret(self):
        dashboard = (ROOT / "k8s" / "dashboard-deployment.yaml").read_text(encoding="utf-8")
        self.assertRegex(
            dashboard,
            r"(?s)- name: AURA_DASHBOARD_AUTH_TOKEN\s+valueFrom:\s+secretKeyRef:\s+"
            r"name: aura-secrets\s+key: AURA_DASHBOARD_AUTH_TOKEN",
        )
        # Ensure it is required (no optional: true)
        token_match = re.search(
            r"- name: AURA_DASHBOARD_AUTH_TOKEN\s+valueFrom:\s+secretKeyRef:\s+name: aura-secrets\s+key: AURA_DASHBOARD_AUTH_TOKEN(?:\s+optional:\s*true)?",
            dashboard,
        )
        self.assertIsNotNone(token_match)
        self.assertNotIn("optional: true", token_match.group(0))

    def test_gpu_image_uses_supported_python_in_an_isolated_venv(self):
        dockerfile = (ROOT / "Dockerfile.gpu").read_text(encoding="utf-8")
        build_instructions = "\n".join(
            line for line in dockerfile.splitlines() if not line.lstrip().startswith("#")
        )

        self.assertNotIn("python3.12", build_instructions)
        self.assertRegex(dockerfile, r"(?m)^\s*python3\s*\\$")
        self.assertRegex(dockerfile, r"(?m)^\s*python3-venv\s*\\$")
        self.assertIn("RUN python3 -m venv /opt/aura-venv", dockerfile)
        self.assertIn('ENV PATH="/opt/aura-venv/bin:${PATH}"', dockerfile)
        self.assertLess(
            dockerfile.index("RUN python3 -m venv /opt/aura-venv"),
            dockerfile.index("RUN python -m pip install --upgrade pip"),
        )
        self.assertIn('CMD ["python", "-m", "uvicorn"', dockerfile)

    def test_gpu_deployment_receives_config_secret_and_persistent_slm_assets(self):
        gpu = (ROOT / "k8s" / "gpu-deployment.yaml").read_text(encoding="utf-8")
        configmap = (ROOT / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

        self.assertRegex(
            gpu,
            r"(?s)envFrom:\s*\n\s*- configMapRef:\s*\n\s+name: aura-config",
        )
        self.assertRegex(
            gpu,
            r"(?s)- name: AURA_GPU_SERVICE_AUTH_TOKEN\s+valueFrom:\s+secretKeyRef:\s+"
            r"name: aura-secrets\s+key: AURA_GPU_SERVICE_AUTH_TOKEN",
        )
        self.assertIn("mountPath: /app/slm", gpu)
        self.assertIn("claimName: gpu-pvc", gpu)
        self.assertIn('SLM_MODEL_DIR: "/app/slm"', configmap)
        self.assertIn('SLM_MODEL_PATH: "/app/slm/aura_flash_v5.pth"', configmap)
        self.assertRegex(
            gpu,
            r"(?s)livenessProbe:\s*\n\s*httpGet:\s*\n\s*path:\s*/live\s*\n\s*port:\s*8001",
        )
        self.assertRegex(
            gpu,
            r"(?s)readinessProbe:\s*\n\s*httpGet:\s*\n\s*path:\s*/ready\s*\n\s*port:\s*8001",
        )

    def test_cpu_brain_does_not_claim_unavailable_local_models(self):
        brain = (ROOT / "k8s" / "brain-deployment.yaml").read_text(encoding="utf-8")
        configmap = (ROOT / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

        self.assertIn('AURA_LOCAL_LLM_ENABLED: "false"', configmap)
        self.assertNotIn("GEMMA_MODEL_PATH", configmap)
        self.assertNotIn("/app/models/Gemma", brain)
        self.assertNotIn("claimName: gemma-pvc", brain)
        self.assertNotIn("/app/core/engine/nanogpt", brain)

        # Required API_KEY and AURA_GPU_SERVICE_AUTH_TOKEN
        self.assertRegex(
            brain,
            r"(?s)- name: API_KEY\s+valueFrom:\s+secretKeyRef:\s+"
            r"name: aura-secrets\s+key: API_KEY",
        )
        self.assertRegex(
            brain,
            r"(?s)- name: AURA_GPU_SERVICE_AUTH_TOKEN\s+valueFrom:\s+secretKeyRef:\s+"
            r"name: aura-secrets\s+key: AURA_GPU_SERVICE_AUTH_TOKEN",
        )

        for secret_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertRegex(
                brain,
                rf"(?s)- name: {secret_name}\s+valueFrom:\s+secretKeyRef:\s+"
                rf"name: aura-secrets\s+key: {secret_name}\s+optional: true",
            )

    def test_aura_secrets_example_declares_all_keys_without_real_secrets(self):
        secrets_example = (ROOT / "k8s" / "aura-secrets.example.yaml").read_text(encoding="utf-8")
        self.assertIn('API_KEY: "YOUR_REAL_API_KEY"', secrets_example)
        self.assertIn('OPENAI_API_KEY: ""', secrets_example)
        self.assertIn('ANTHROPIC_API_KEY: ""', secrets_example)
        self.assertIn('AURA_DASHBOARD_AUTH_TOKEN: ""', secrets_example)
        self.assertIn('AURA_GPU_SERVICE_AUTH_TOKEN: ""', secrets_example)

    def test_deploy_script_checks_all_image_builds_and_native_failures(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        self.assertIn('$ErrorActionPreference = "Stop"', deploy_script)
        self.assertIn("function Invoke-CheckedNative", deploy_script)
        self.assertIn("if ($LASTEXITCODE -ne 0)", deploy_script)
        self.assertRegex(deploy_script, r'(?m)^\s*throw\s+"Native command failed')

        expected_images = {
            "Dockerfile.brain": "aura/brain:latest",
            "Dockerfile.gpu": "aura/gpuservice:latest",
            "Dockerfile.dashboard": "aura/dashboard:latest",
            "Dockerfile.chroma": "aura/chromadb:latest",
        }
        build_lines = [
            line.strip()
            for line in deploy_script.splitlines()
            if line.strip().startswith("Invoke-CheckedNative docker")
        ]
        self.assertEqual(len(build_lines), len(expected_images))
        for dockerfile, image in expected_images.items():
            self.assertIn(
                f'Invoke-CheckedNative docker @("build", "-f", "{dockerfile}", '
                f'"-t", "{image}", ".")',
                build_lines,
            )

    def test_deploy_script_manages_secrets_safely_without_echoing(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        self.assertIn("function Invoke-CheckedSecretStdin", deploy_script)
        self.assertIn("function New-AuraAuthToken", deploy_script)

        # Secret values travel over stdin, never through the native process
        # command line, and failures do not interpolate either channel.
        secret_native_block = deploy_script[
            deploy_script.index("function Invoke-CheckedSecretStdin") : deploy_script.index(
                "function New-AuraAuthToken"
            )
        ]
        failure_message = secret_native_block.split("throw")[1]
        self.assertNotIn("$Arguments", failure_message)
        self.assertNotIn("$InputText", failure_message)
        self.assertIn("Secret command failed", secret_native_block)
        self.assertIn("$InputText | & $Executable @Arguments", secret_native_block)
        self.assertNotIn("--from-literal", deploy_script)
        self.assertNotIn('"-p", $patchJson', deploy_script)
        self.assertIn(
            'Invoke-CheckedSecretStdin kubectl @("create", "-f", "-")',
            deploy_script,
        )
        self.assertIn(
            'Invoke-CheckedSecretStdin kubectl @("replace", "-f", "-")',
            deploy_script,
        )

        # Secret creation logic includes tokens
        self.assertIn("AURA_DASHBOARD_AUTH_TOKEN", deploy_script)
        self.assertIn("AURA_GPU_SERVICE_AUTH_TOKEN", deploy_script)
        self.assertIn("AURA_EVENT_JOURNAL_HMAC_KEY", deploy_script)

        # Tokens and raw/decoded secrets are not echoed by Write-Host, Write-Output, Write-Warning, or throw
        sensitive_vars = [
            "$dashboardToken",
            "$gpuToken",
            "$newToken",
            "$API_KEY",
            "$secretManifestJson",
            "$secretData",
            "$InputText",
            "$decoded",
            "$Base64Value",
        ]
        for line in deploy_script.splitlines():
            stripped = line.strip()
            if any(
                stripped.startswith(prefix)
                for prefix in ("Write-Host", "Write-Output", "Write-Warning", "Write-Error", "throw")
            ):
                for var in sensitive_vars:
                    self.assertNotIn(var, stripped, f"Sensitive variable {var} leaked in line: {stripped}")

        # End of script prints command to retrieve dashboard token
        self.assertIn("AURA_DASHBOARD_AUTH_TOKEN", deploy_script.split("=== DEPLOY XONG ===")[1])

    def test_deploy_script_repairs_tokens_without_dropping_existing_secret_data(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        self.assertIn("foreach ($property in $dataObj.PSObject.Properties)", deploy_script)
        self.assertIn(
            "$secretData[$property.Name] = [string]$property.Value",
            deploy_script,
        )
        self.assertIn("$secretObj.data = $secretData", deploy_script)
        self.assertIn(
            "$secretManifestJson = $secretObj | ConvertTo-Json",
            deploy_script,
        )
        self.assertIn("if ($secretChanged)", deploy_script)
        self.assertNotIn("kubectl patch", deploy_script)

    def test_deploy_script_secret_query_uses_ignore_not_found_and_guards_exit_code(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        # Query must use --ignore-not-found so missing secret does not fail
        self.assertRegex(
            deploy_script,
            r'kubectl\s+get\s+secret\s+aura-secrets\s+-n\s+aura\s+-o\s+json\s+--ignore-not-found',
        )

        # Must immediately check $LASTEXITCODE and fail generically on non-zero
        secret_query_idx = deploy_script.index("kubectl get secret aura-secrets")
        secret_block = deploy_script[secret_query_idx : deploy_script.index("if (-not $existingSecretJson)")]

        self.assertIn("if ($LASTEXITCODE -ne 0)", secret_block)
        self.assertRegex(secret_block, r'throw\s+"Failed to query secret aura-secrets')

    def test_deploy_script_rng_is_disposed_in_finally_block(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        token_fn_start = deploy_script.index("function New-AuraAuthToken")
        token_fn_end = deploy_script.index("function Test-AuraValidAuthToken", token_fn_start)
        token_fn = deploy_script[token_fn_start:token_fn_end]

        self.assertIn("[System.Security.Cryptography.RandomNumberGenerator]::Create()", token_fn)
        self.assertIn("try {", token_fn)
        self.assertIn("finally {", token_fn)
        self.assertRegex(token_fn, r"\$rng\.Dispose\(\)")

    def test_deploy_script_validates_and_regenerates_invalid_or_empty_tokens(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        self.assertIn("function Test-AuraValidAuthToken", deploy_script)

        # Token validation function checks
        val_fn_start = deploy_script.index("function Test-AuraValidAuthToken")
        val_fn_end = deploy_script.index("# ---- BUOC 0:", val_fn_start)
        val_fn = deploy_script[val_fn_start:val_fn_end]

        self.assertIn("[Convert]::FromBase64String", val_fn)
        self.assertIn("32", val_fn)
        self.assertIn("256", val_fn)
        self.assertIn("a-zA-Z0-9", val_fn)

        # All required internal keys are validated and regenerated when
        # missing/invalid; unrelated entries remain in the copied data map.
        token_keys_block = deploy_script[
            deploy_script.index("$tokenKeys = @(") : deploy_script.index(
                "foreach ($tokenKey in $tokenKeys)"
            )
        ]
        for key in (
            "AURA_DASHBOARD_AUTH_TOKEN",
            "AURA_GPU_SERVICE_AUTH_TOKEN",
            "AURA_EVENT_JOURNAL_HMAC_KEY",
        ):
            self.assertIn(f'"{key}"', token_keys_block)
        self.assertIn("Test-AuraValidAuthToken", deploy_script)
        self.assertIn("New-AuraAuthToken", deploy_script)
        self.assertIn("$secretChanged = $true", deploy_script)

    def test_unauthenticated_ingress_is_explicitly_opt_in(self):
        deploy_script = (ROOT / "k8s" / "deploy.ps1").read_text(encoding="utf-8")

        gate = 'if ($env:AURA_ENABLE_UNSAFE_INGRESS -eq "true") {'
        gate_start = deploy_script.index(gate)
        safe_default_start = deploy_script.index("} else {", gate_start)
        opt_in_block = deploy_script[gate_start:safe_default_start]

        self.assertIn("has no authentication/TLS", opt_in_block)
        self.assertIn('Invoke-CheckedNative kubectl @("apply", "-f", "k8s/ingress.yaml")', opt_in_block)
        self.assertEqual(deploy_script.count('"k8s/ingress.yaml"'), 1)
        self.assertIn("[SAFE DEFAULT]", deploy_script[safe_default_start:])


if __name__ == "__main__":
    unittest.main()
