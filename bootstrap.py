import os
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Mapping

import shlex

from core.runtime_paths import (
    LegacyArtifactKind,
    LegacyArtifactManifest,
    RuntimePathError,
    RuntimePaths,
    discover_legacy_artifacts,
)

# Phase 1: Environment Validation
REQUIRED_PYTHON_VERSION = (3, 12)


def prepare_runtime_layout(
    *,
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[RuntimePaths, LegacyArtifactManifest]:
    """Validate and explicitly create the empty canonical runtime layout.

    This is deliberately the only A1 code path that calls ``mkdir``.  It does
    not read artifact contents, move, migrate, or delete legacy artifacts.
    Discovery beforehand performs only bounded non-recursive metadata checks;
    a same-kind ambiguity must be resolved by a later migration workflow.
    """

    project_dir = Path(base_dir) if base_dir is not None else Path(__file__).parent
    environment = os.environ if env is None else env
    paths = RuntimePaths.from_env(
        base_dir=project_dir,
        env=environment,
        cwd=Path.cwd() if cwd is None else cwd,
    )
    manifest = discover_legacy_artifacts(paths, environment)
    if manifest.has_conflicts:
        kinds = ", ".join(kind.value for kind in manifest.conflicts)
        raise RuntimePathError(f"legacy artifact conflicts require migration: {kinds}")
    for directory in (
        paths.data_dir,
        paths.control_db_path.parent,
        paths.state_generations_dir,
        paths.memory_chroma_dir,
        paths.chat_spool_dir,
        paths.event_journal_dir,
        paths.recovery_dir,
        paths.logs_dir,
        paths.cache_dir,
        paths.temp_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths, manifest


def _report_unpromoted_legacy_sources(manifest: LegacyArtifactManifest) -> None:
    """Report one-source snapshots deterministically without migrating them."""

    for kind in LegacyArtifactKind:
        sources = manifest.populated_for(kind)
        if len(sources) == 1:
            print(
                f"Legacy {kind.value} source detected at {sources[0]} "
                "(not migrated or promoted)."
            )

def check_git_config():
    """Check for 'dubious ownership' issues on Windows/WSL environments."""
    try:
        subprocess.check_output(["git", "status"], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        if b"dubious ownership" in e.output:
            print("⚠️ Warning: Git 'dubious ownership' detected.")
            print("Run: git config --global --add safe.directory " + os.getcwd().replace("\\", "/"))
    except FileNotFoundError:
        pass # Git not installed, skip

def check_python_version():
    if sys.version_info < REQUIRED_PYTHON_VERSION:
        print(f"❌ Error: Aura requires Python {REQUIRED_PYTHON_VERSION[0]}.{REQUIRED_PYTHON_VERSION[1]} or higher.")
        print(f"Current version: {sys.version}")
        sys.exit(1)

def run_command(cmd):
    print(f"Executing: {cmd}")
    try:
        args = shlex.split(cmd)
        subprocess.check_call(args)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return False
    return True

def is_venv_valid(venv_path):
    python_exe = os.path.join(venv_path, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_path, "bin", "python")
    if not os.path.exists(python_exe):
        return False
    try:
        # Check if python can actually run
        subprocess.check_call([python_exe, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def main():
    print("=== Aura Bootstrap & Recovery Tool ===")

    try:
        paths, manifest = prepare_runtime_layout()
    except RuntimePathError as exc:
        print(f"Runtime layout validation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Canonical runtime data directory: {paths.data_dir}")
    _report_unpromoted_legacy_sources(manifest)
    
    force_recreate = "--force" in sys.argv
    
    # Standard venvs to manage
    venvs = [".venv", ".venv_aura"]
    
    for venv in venvs:
        if os.path.exists(venv):
            if force_recreate or not is_venv_valid(venv):
                print(f"Removing broken or old venv: {venv}")
                shutil.rmtree(venv, ignore_errors=True)
        
        if not os.path.exists(venv):
            print(f"Creating virtual environment: {venv}")
            if not run_command(f"{sys.executable} -m venv {venv}"):
                print(f"Failed to create {venv}. Please ensure Python 3.12+ is installed.")
                continue
    
    # 2. Install dependencies (standard .venv for engine)
    pip_path = os.path.join(".venv", "Scripts", "pip.exe") if os.name == "nt" else os.path.join(".venv", "bin", "pip")
    if os.path.exists(pip_path):
        print("Installing main engine dependencies...")
        run_command(f"{pip_path} install .")
    
    # 3. Install SLM dependencies (.venv_aura for Torch/GPU work)
    pip_aura = os.path.join(".venv_aura", "Scripts", "pip.exe") if os.name == "nt" else os.path.join(".venv_aura", "bin", "pip")
    if os.path.exists(pip_aura):
        print("Installing SLM (Torch) dependencies...")
        # Since we use pyproject.toml now, we can install the same set or specialized ones
        run_command(f"{pip_aura} install .")

    # 4. Setup .env if not exists
    if not os.path.exists(".env"):
        print("Initializing .env from .env.example...")
        if os.path.exists(".env.example"):
            shutil.copy(".env.example", ".env")
        else:
            with open(".env", "w") as f:
                f.write("API_KEY=your_gemini_key_here\nMODEL_NAME=gemini-3.0-flash\n")

    print("\n[SUCCESS] Aura environment is repaired/initialized!")
    print("1. Run services: .\\start_services.ps1")
    print("2. Run Aura: .\\.venv\\Scripts\\python.exe main.py")
    print("3. Eval SLM: .\\.venv_aura\\Scripts\\python.exe scripts/eval_slm.py")
    return 0

if __name__ == "__main__":
    check_python_version()
    check_git_config()
    
    # ─── 1. Setup Master Venv (.venv) ────────────────────────────────
    raise SystemExit(main())
