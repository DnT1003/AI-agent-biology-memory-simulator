"""Regression contracts for the local and dashboard release entry points."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _stage_dashboard_docker_payload(destination: Path) -> str:
    """Apply this Dockerfile's COPY instructions to a temporary app root."""

    dockerfile = (ROOT / "Dockerfile.dashboard").read_text(encoding="utf-8")
    for raw_line in dockerfile.splitlines():
        if not raw_line.startswith("COPY "):
            continue
        tokens = shlex.split(raw_line, posix=True)
        sources, raw_target = tokens[1:-1], tokens[-1]
        target = destination / raw_target.removeprefix("./").rstrip("/")

        if len(sources) > 1:
            target.mkdir(parents=True, exist_ok=True)
            for source in sources:
                source_path = ROOT / source.rstrip("/")
                shutil.copy2(source_path, target / source_path.name)
            continue

        source_path = ROOT / sources[0].rstrip("/")
        if source_path.is_dir():
            shutil.copytree(
                source_path,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
    return dockerfile


def _config_api_key(**updates: str) -> str:
    env = os.environ.copy()
    env.pop("GEMINI_API_KEY", None)
    env.pop("API_KEY", None)
    env.update(updates)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from config import Config; print(json.dumps(Config.API_KEY))",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout.strip())


def test_dashboard_image_payload_imports_every_runtime_module(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    dockerfile = _stage_dashboard_docker_payload(app_root)

    expected_core = {
        "core/__init__.py",
        "core/chat_spool.py",
        "core/event_journal.py",
        "core/interaction_policy.py",
        "core/logger.py",
        "core/settings_manager.py",
        "core/utils.py",
    }
    copy_tokens = [
        shlex.split(line, posix=True)
        for line in dockerfile.splitlines()
        if line.startswith("COPY ")
    ]
    copied_core = {
        source
        for tokens in copy_tokens
        for source in tokens[1:-1]
        if source.startswith("core/")
    }
    assert copied_core == expected_core
    assert '"colorama>=0.4.6"' in dockerfile

    output_dir = app_root / "outputs"
    output_dir.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["AURA_OUTPUT_DIR"] = str(output_dir)
    env["AURA_EVENT_JOURNAL_ENABLED"] = "false"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import dashboard.server; "
                "import core.chat_spool, core.event_journal, "
                "core.interaction_policy, core.logger; "
                "print('dashboard-payload-ok')"
            ),
        ],
        cwd=app_root,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "dashboard-payload-ok" in result.stdout


def test_gpu_launcher_uses_public_health_contract_and_fails_closed() -> None:
    script = (ROOT / "start_services.ps1").read_text(encoding="utf-8")
    gpu_section = script.split(
        'Write-Host "[2/2] Kiem tra GPU Microservice tai port 8001..."', 1
    )[1]

    live_probe = gpu_section.index("http://127.0.0.1:8001/live")
    launch_guard = gpu_section.index("if (-not $gpuLive)")
    launch = gpu_section.index("Start-Process")
    ready_probe = gpu_section.index("http://127.0.0.1:8001/ready")
    assert live_probe < launch_guard < launch < ready_probe
    assert "http://127.0.0.1:8001/health" not in gpu_section
    assert gpu_section.count("Start-Process") == 1
    assert '$resp.status -eq "ready"' in gpu_section
    assert "$resp.ready -eq $true" in gpu_section
    assert "if (-not $gpuReady)" in gpu_section
    failure_block = gpu_section.split("if (-not $gpuReady)", 1)[1].split(
        "#", 1
    )[0]
    assert "exit 1" in failure_block


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not installed")
def test_service_launcher_has_valid_powershell_ast() -> None:
    env = os.environ.copy()
    env["AURA_SCRIPT_TO_PARSE"] = str(ROOT / "start_services.ps1")
    parser_command = (
        "$tokens = $null; $errors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:AURA_SCRIPT_TO_PARSE, [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }; "
        "exit 1 }"
    )
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            parser_command,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_gpu_launcher_fails_fast_only_for_the_child_it_started() -> None:
    script = (ROOT / "start_services.ps1").read_text(encoding="utf-8")
    gpu_section = script.split(
        'Write-Host "[2/2] Kiem tra GPU Microservice tai port 8001..."', 1
    )[1]

    assert "$gpuStartedHere = $false" in gpu_section
    assert "$gpuJob = $null" in gpu_section
    launch = gpu_section.index("Start-Process")
    started = gpu_section.index("$gpuStartedHere = $true")
    ready_probe = gpu_section.index("http://127.0.0.1:8001/ready")
    child_exit_guard = (
        "if ($gpuStartedHere -and ($null -ne $gpuJob) -and $gpuJob.HasExited)"
    )
    guard = gpu_section.index(child_exit_guard)
    sleep = gpu_section.index("Start-Sleep", guard)
    assert launch < started < ready_probe < guard < sleep

    fail_fast_block = gpu_section.split(child_exit_guard, 1)[1].split("}", 1)[0]
    assert "[ERROR]" in fail_fast_block
    assert "Kiem tra log" in fail_fast_block
    assert "exit 1" in fail_fast_block


def test_start_web_propagates_service_launcher_failure(monkeypatch) -> None:
    import start_web

    observed = {}

    def fail_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        raise subprocess.CalledProcessError(23, command)

    monkeypatch.setattr(start_web.subprocess, "run", fail_run)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        start_web.run_services()

    assert raised.value.returncode == 23
    assert observed["kwargs"]["check"] is True
    assert observed["command"][-2] == "-File"
    assert Path(observed["command"][-1]).resolve() == (ROOT / "start_services.ps1").resolve()


def test_gemini_api_key_is_canonical_with_legacy_fallback() -> None:
    assert _config_api_key(GEMINI_API_KEY="canonical-key", API_KEY="legacy-key") == (
        "canonical-key"
    )
    assert _config_api_key(API_KEY="legacy-key") == "legacy-key"
