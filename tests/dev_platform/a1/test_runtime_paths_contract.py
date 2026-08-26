from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bootstrap import prepare_runtime_layout
from core.runtime_paths import (
    LegacyArtifactKind,
    RuntimePathError,
    RuntimePaths,
    _validate_path_text,
    discover_legacy_artifacts,
)


def make_paths(tmp_path: Path, env: dict[str, str] | None = None, cwd: Path | None = None) -> RuntimePaths:
    return RuntimePaths.from_env(
        base_dir=tmp_path / "project",
        env={} if env is None else env,
        cwd=tmp_path / "legacy-cwd" if cwd is None else cwd,
    )


def test_exact_canonical_field_mapping(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, {"AURA_DATA_DIR": "durable"})
    root = (tmp_path / "project" / "durable").resolve()

    assert paths.data_dir == root
    assert paths.manifest_path == root / "manifest.json"
    assert paths.control_db_path == root / "ledger" / "aura-control.sqlite3"
    assert paths.writer_lease_path == root / "ledger" / "writer.lock"
    assert paths.state_dir == root / "state"
    assert paths.state_generations_dir == root / "state" / "generations"
    assert paths.state_current_path == root / "state" / "CURRENT"
    assert paths.memory_chroma_dir == root / "memory" / "chroma"
    assert paths.chat_spool_dir == root / "transport" / "chat-spool"
    assert paths.event_journal_dir == root / "audit" / "event-journal"
    assert paths.recovery_dir == root / "recovery"
    assert paths.logs_dir == root / "runtime" / "logs"
    assert paths.cache_dir == root / "runtime" / "cache"
    assert paths.temp_dir == root / "runtime" / "tmp"
    assert all(value.is_absolute() for value in vars(paths).values() if isinstance(value, Path))


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"AURA_DATA_DIR": "data", "AURA_OUTPUT_DIR": "output"}, "data"),
        ({"AURA_DATA_DIR": " \t ", "AURA_OUTPUT_DIR": "output"}, "output"),
        ({"AURA_DATA_DIR": "", "AURA_OUTPUT_DIR": " \n "}, "outputs"),
    ],
)
def test_precedence_and_whitespace(tmp_path: Path, env: dict[str, str], expected: str) -> None:
    assert make_paths(tmp_path, env).data_dir == (tmp_path / "project" / expected).resolve()


def test_relative_root_is_based_on_base_dir_not_cwd(tmp_path: Path) -> None:
    env = {"AURA_DATA_DIR": "relative-root"}
    first = make_paths(tmp_path, env, tmp_path / "one")
    second = make_paths(tmp_path, env, tmp_path / "two")
    assert first.data_dir == second.data_dir == (tmp_path / "project" / "relative-root").resolve()


def test_relative_base_dir_is_rejected_without_reading_process_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimePathError, match="base_dir must be absolute"):
        RuntimePaths.from_env(base_dir=Path("relative-project"), env={})


def test_implicit_legacy_cwd_is_the_normalized_base_dir(tmp_path: Path) -> None:
    base = (tmp_path / "project").resolve()
    paths = RuntimePaths.from_env(base_dir=base, env={})
    manifest = discover_legacy_artifacts(paths, {})
    assert manifest.candidates_for(LegacyArtifactKind.IDENTITY) == (base / "identity.json",)


@pytest.mark.skipif(os.name != "nt", reason="Windows grammar is host-specific")
@pytest.mark.parametrize("value", [r"D:relative", r"\relative"])
def test_windows_drive_and_root_relative_values_are_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(RuntimePathError):
        make_paths(tmp_path, {"AURA_DATA_DIR": value})


@pytest.mark.skipif(os.name != "nt", reason="Windows grammar is host-specific")
@pytest.mark.parametrize("value", ["CON", "bad<name", "trailing. ", "control\x01"])
def test_windows_invalid_components_are_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(RuntimePathError):
        make_paths(tmp_path, {"AURA_DATA_DIR": value})


@pytest.mark.parametrize("value", ["a:b", "bad<name", "CON"])
def test_posix_validation_allows_windows_only_names(value: str) -> None:
    _validate_path_text(value, label="path", windows=False)


def test_home_expansion_is_single_and_environment_syntax_is_literal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", os.fspath(home))
    monkeypatch.setenv("USERPROFILE", os.fspath(home))
    paths = make_paths(tmp_path, {"AURA_DATA_DIR": "~/$AURA_NESTED/%AURA_NESTED%"})
    assert paths.data_dir == (home / "$AURA_NESTED" / "%AURA_NESTED%").resolve()


@pytest.mark.parametrize("value", ["\x00bad", "/"])
def test_roots_and_nul_are_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(RuntimePathError):
        make_paths(tmp_path, {"AURA_DATA_DIR": value})


def test_invalid_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimePathError):
        make_paths(tmp_path, {"AURA_DATA_DIR": "\ud800"})


def test_from_env_is_pure_and_does_not_create_the_layout(tmp_path: Path) -> None:
    base = tmp_path / "empty-project"
    before = list(tmp_path.rglob("*"))
    paths = RuntimePaths.from_env(base_dir=base, env={"AURA_DATA_DIR": "new-data"})
    after = list(tmp_path.rglob("*"))
    assert paths.data_dir == (base / "new-data").resolve()
    assert before == after == []


def test_legacy_discovery_deduplicates_canonical_identical_paths(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    manifest = discover_legacy_artifacts(
        paths,
        {"AURA_EVENT_JOURNAL_DIR": "outputs/./event_journal"},
    )
    journal = manifest.candidates_for(LegacyArtifactKind.JOURNAL)
    assert journal == ((tmp_path / "project" / "outputs" / "event_journal").resolve(),)
    assert LegacyArtifactKind.JOURNAL not in manifest.conflicts


def test_same_kind_legacy_candidates_are_a_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    manifest = discover_legacy_artifacts(
        paths,
        {"AURA_CHAT_SPOOL_DIR": "elsewhere/chat"},
    )
    assert manifest.has_conflicts
    assert LegacyArtifactKind.TRANSPORTS in manifest.conflicts


def test_different_artifact_kinds_in_different_roots_are_not_a_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    manifest = discover_legacy_artifacts(
        paths,
        {
            "AURA_EVENT_JOURNAL_DIR": "outputs/event_journal",
            "AURA_CHAT_SPOOL_DIR": "outputs/chat_spool",
        },
    )
    assert not manifest.has_conflicts


def test_config_import_is_non_creating_and_projects_compatibility_paths(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    data_dir = tmp_path / "does-not-exist-canonical"
    environment = os.environ.copy()
    environment["AURA_DATA_DIR"] = os.fspath(data_dir)
    environment["AURA_OUTPUT_DIR"] = "legacy-output"
    environment["AURA_CHAT_SPOOL_DIR"] = "legacy-chat"
    environment["AURA_EVENT_JOURNAL_DIR"] = "legacy-journal"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from config import Config; "
                "print(Config.RUNTIME_PATHS.data_dir); print(Config.OUTPUT_DIR); "
                "print(Config.CHROMA_DB_PATH); print(Config.CHAT_SPOOL_DIR); "
                "print(Config.EVENT_JOURNAL_DIR); print(Config.CONTROL_DB_PATH); "
                "print(Config.WRITER_LEASE_PATH)"
            ),
        ],
        cwd=project_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        os.fspath(data_dir.resolve()),
        "legacy-output",
        os.fspath(Path("legacy-output") / "chroma_db"),
        os.fspath((project_root / "legacy-chat").resolve()),
        os.fspath((project_root / "legacy-journal").resolve()),
        os.fspath(data_dir.resolve() / "ledger" / "aura-control.sqlite3"),
        os.fspath(data_dir.resolve() / "ledger" / "writer.lock"),
    ]
    assert not data_dir.exists()


def test_full_repository_canonical_config_binding_uses_runtimepaths() -> None:
    from config import Config

    assert isinstance(Config.RUNTIME_PATHS, RuntimePaths)


def test_dashboard_staged_payload_imports_config_without_runtime_paths(tmp_path: Path) -> None:
    """The released dashboard image deliberately excludes canonical runtime code."""

    project_root = Path(__file__).resolve().parents[3]
    staged = tmp_path / "dashboard-image"
    staged.mkdir()
    expected_core = (
        "__init__.py",
        "chat_spool.py",
        "event_journal.py",
        "interaction_policy.py",
        "logger.py",
        "settings_manager.py",
        "utils.py",
    )
    shutil.copy2(project_root / "config.py", staged / "config.py")
    (staged / "core").mkdir()
    for name in expected_core:
        shutil.copy2(project_root / "core" / name, staged / "core" / name)
    shutil.copytree(project_root / "dashboard", staged / "dashboard")

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from dashboard.server import app; from config import Config; print(Config.OUTPUT_DIR)",
        ],
        cwd=staged,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not (staged / "core" / "runtime_paths.py").exists()


def test_dashboard_dockerfile_keeps_exact_released_core_payload() -> None:
    project_root = Path(__file__).resolve().parents[3]
    dockerfile = (project_root / "Dockerfile.dashboard").read_text(encoding="utf-8")
    assert (
        "COPY core/__init__.py core/chat_spool.py core/event_journal.py "
        "core/interaction_policy.py core/logger.py core/settings_manager.py "
        "core/utils.py ./core/"
    ) in dockerfile
    assert "core/runtime_paths.py" not in dockerfile


def _launcher_environment(**updates: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("AURA_DATA_DIR", None)
    environment.pop("AURA_OUTPUT_DIR", None)
    environment.update(updates)
    return environment


def _run_batch_resolver(project_root: Path, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd.exe", "/d", "/c", os.fspath(project_root / "scripts" / "run_chroma_server.bat"), "--print-chroma-path"],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _run_powershell_resolver(project_root: Path, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", os.fspath(project_root / "start_services.ps1"), "--print-chroma-path"],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


@pytest.mark.skipif(os.name != "nt", reason="launchers are Windows scripts")
@pytest.mark.parametrize(
    ("environment", "suffix"),
    [
        ({"AURA_DATA_DIR": "canonical", "AURA_OUTPUT_DIR": "legacy"}, Path("canonical/memory/chroma")),
        ({"AURA_DATA_DIR": "\t", "AURA_OUTPUT_DIR": "legacy"}, Path("legacy/chroma_db")),
        ({"AURA_OUTPUT_DIR": "legacy"}, Path("legacy/chroma_db")),
        ({}, Path("outputs/chroma_db")),
    ],
)
def test_executable_launchers_resolve_precedence_independent_of_cwd(
    tmp_path: Path, environment: dict[str, str], suffix: Path
) -> None:
    project_root = Path(__file__).resolve().parents[3]
    first_cwd = tmp_path / "first"
    second_cwd = tmp_path / "second"
    first_cwd.mkdir()
    second_cwd.mkdir()
    expected = (project_root / suffix).resolve()
    for runner in (_run_batch_resolver, _run_powershell_resolver):
        outputs = []
        for cwd in (first_cwd, second_cwd):
            result = runner(project_root, cwd, _launcher_environment(**environment))
            assert result.returncode == 0, result.stderr
            outputs.append(Path(result.stdout.strip()))
        assert outputs == [expected, expected]


@pytest.mark.skipif(os.name != "nt", reason="launchers are Windows scripts")
@pytest.mark.parametrize("value", [r"D:relative", r"\relative", "C:\\", "CON"])
def test_executable_launchers_reject_invalid_windows_roots(tmp_path: Path, value: str) -> None:
    project_root = Path(__file__).resolve().parents[3]
    for runner in (_run_batch_resolver, _run_powershell_resolver):
        result = runner(project_root, tmp_path, _launcher_environment(AURA_DATA_DIR=value))
        assert result.returncode != 0


@pytest.mark.skipif(os.name != "nt", reason="UNC semantics are Windows-specific")
@pytest.mark.parametrize("value", [r"\\server\share\aura", "//server/share/aura"])
def test_executable_launchers_accept_unc_absolute_root(tmp_path: Path, value: str) -> None:
    project_root = Path(__file__).resolve().parents[3]
    environment = _launcher_environment(AURA_DATA_DIR=value)
    for runner in (_run_batch_resolver, _run_powershell_resolver):
        result = runner(project_root, tmp_path, environment)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().lower().endswith(r"\aura\memory\chroma")


def test_launchers_and_k8s_preserve_legacy_compatibility_contract() -> None:
    project_root = Path(__file__).resolve().parents[3]
    powershell = (project_root / "start_services.ps1").read_text(encoding="utf-8")
    batch = (project_root / "scripts" / "run_chroma_server.bat").read_text(encoding="utf-8")
    assert "AURA_DATA_DIR" in powershell
    assert "AURA_OUTPUT_DIR" in powershell
    assert "RuntimePaths.from_env" in powershell
    assert "chroma_db" in powershell
    # The batch resolver delegates precedence to RuntimePaths instead of
    # duplicating environment parsing in cmd.exe.
    assert "RuntimePaths.from_env" in batch
    assert "chroma_db" in batch
    assert "memory_chroma_dir" in powershell
    assert "memory_chroma_dir" in batch
    configmap = (project_root / "k8s" / "configmap.yaml").read_text(encoding="utf-8")
    dashboard = (project_root / "k8s" / "dashboard-deployment.yaml").read_text(encoding="utf-8")
    for source in (configmap, dashboard):
        assert "AURA_DATA_DIR" in source
        assert "AURA_OUTPUT_DIR" in source
        assert "/app/outputs" in source


def test_explicit_bootstrap_creates_layout_only_after_validation(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paths, manifest = prepare_runtime_layout(
        base_dir=tmp_path / "project",
        cwd=tmp_path / "project",
        env={"AURA_DATA_DIR": os.fspath(data_dir)},
    )
    assert not manifest.has_conflicts
    assert paths.control_db_path.parent.is_dir()
    assert paths.state_generations_dir.is_dir()
    assert paths.memory_chroma_dir.is_dir()
    assert not paths.manifest_path.exists()
