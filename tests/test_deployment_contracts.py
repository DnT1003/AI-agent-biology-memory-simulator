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

    def test_dashboard_ports_match_runtime_contract(self):
        dashboard = (ROOT / "k8s" / "dashboard-deployment.yaml").read_text(encoding="utf-8")

        self.assertIn("containerPort: 8050", dashboard)
        self.assertEqual(dashboard.count("port: 8050"), 2)
        self.assertIn("targetPort: 8050", dashboard)

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

    def test_gpu_deployment_receives_config_and_persistent_slm_assets(self):
        gpu = (ROOT / "k8s" / "gpu-deployment.yaml").read_text(encoding="utf-8")
        configmap = (ROOT / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

        self.assertRegex(
            gpu,
            r"(?s)envFrom:\s*\n\s*- configMapRef:\s*\n\s+name: aura-config",
        )
        self.assertIn("mountPath: /app/slm", gpu)
        self.assertIn("claimName: gpu-pvc", gpu)
        self.assertIn('SLM_MODEL_DIR: "/app/slm"', configmap)
        self.assertIn('SLM_MODEL_PATH: "/app/slm/aura_flash_v5.pth"', configmap)

    def test_cpu_brain_does_not_claim_unavailable_local_models(self):
        brain = (ROOT / "k8s" / "brain-deployment.yaml").read_text(encoding="utf-8")
        configmap = (ROOT / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

        self.assertIn('AURA_LOCAL_LLM_ENABLED: "false"', configmap)
        self.assertNotIn("GEMMA_MODEL_PATH", configmap)
        self.assertNotIn("/app/models/Gemma", brain)
        self.assertNotIn("claimName: gemma-pvc", brain)
        self.assertNotIn("/app/core/engine/nanogpt", brain)

        for secret_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertRegex(
                brain,
                rf"(?s)- name: {secret_name}\s+valueFrom:\s+secretKeyRef:\s+"
                rf"name: aura-secrets\s+key: {secret_name}\s+optional: true",
            )

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
