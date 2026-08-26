from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from bootstrap import prepare_runtime_layout
from bootstrap import _report_unpromoted_legacy_sources
from core.runtime_paths import (
    LegacyArtifactKind,
    LegacyArtifactManifest,
    RuntimePathError,
    RuntimePaths,
    _canonical_legacy_candidate,
    _unresolved_absolute_path,
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


def _write_immediate_entry(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "entry").write_text("present", encoding="utf-8")


def _make_symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except NotImplementedError as exc:
        pytest.skip(f"host cannot create the required symlink: {exc}")
    except OSError as exc:
        unsupported = {errno.ENOSYS, errno.EOPNOTSUPP}
        if os.name == "nt" and getattr(exc, "winerror", None) in {50, 1314}:
            pytest.skip(f"host lacks symlink capability: {exc}")
        if exc.errno in unsupported:
            pytest.skip(f"host lacks symlink capability: {exc}")
        raise


def test_legacy_candidates_remain_when_all_locations_are_absent(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    manifest = discover_legacy_artifacts(
        paths,
        {"AURA_CHAT_SPOOL_DIR": "elsewhere/chat"},
    )
    candidates = manifest.candidates_for(LegacyArtifactKind.TRANSPORTS)
    assert (tmp_path / "project" / "elsewhere" / "chat").resolve() in candidates
    assert manifest.populated_for(LegacyArtifactKind.TRANSPORTS) == ()
    assert not manifest.has_conflicts


def test_one_populated_same_kind_source_does_not_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    populated = tmp_path / "one" / "chat"
    _write_immediate_entry(populated)
    manifest = discover_legacy_artifacts(
        paths,
        {"AURA_CHAT_SPOOL_DIR": os.fspath(populated)},
    )
    assert populated.resolve() in manifest.candidates_for(LegacyArtifactKind.TRANSPORTS)
    assert manifest.populated_for(LegacyArtifactKind.TRANSPORTS) == (populated.resolve(),)
    assert LegacyArtifactKind.TRANSPORTS not in manifest.conflicts


def test_two_populated_same_kind_sources_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    historical_root = tmp_path / "historical-output"
    historical = historical_root / "chat_spool"
    override = tmp_path / "override" / "chat"
    _write_immediate_entry(historical)
    _write_immediate_entry(override)
    manifest = discover_legacy_artifacts(
        paths,
        {
            "AURA_OUTPUT_DIR": os.fspath(historical_root),
            "AURA_CHAT_SPOOL_DIR": os.fspath(override),
        },
    )
    assert manifest.conflicts[LegacyArtifactKind.TRANSPORTS] == (
        historical.resolve(),
        override.resolve(),
    )
    assert manifest.populated_for(LegacyArtifactKind.TRANSPORTS) == manifest.conflicts[
        LegacyArtifactKind.TRANSPORTS
    ]


def test_zero_byte_regular_file_is_a_populated_file_artifact(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    historical_root = tmp_path / "historical-output"
    historical = historical_root / "ego_state.json"
    override = tmp_path / "override" / "ego.json"
    historical.parent.mkdir(parents=True)
    historical.touch()
    override.parent.mkdir(parents=True)
    override.touch()
    manifest = discover_legacy_artifacts(
        paths,
        {
            "AURA_OUTPUT_DIR": os.fspath(historical_root),
            "AURA_EGO_PATH": os.fspath(override),
        },
    )
    assert manifest.conflicts[LegacyArtifactKind.EGO] == (
        historical.resolve(),
        override.resolve(),
    )


def test_empty_directory_is_not_populated_but_nonempty_directory_is(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    historical_root = tmp_path / "historical-output"
    _write_immediate_entry(historical_root / "event_journal")
    empty_override = tmp_path / "empty-journal"
    empty_override.mkdir()
    manifest = discover_legacy_artifacts(
        paths,
        {
            "AURA_OUTPUT_DIR": os.fspath(historical_root),
            "AURA_EVENT_JOURNAL_DIR": os.fspath(empty_override),
        },
    )
    assert LegacyArtifactKind.JOURNAL not in manifest.conflicts


def test_legacy_discovery_rejects_wrong_artifact_type(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    wrong_type = tmp_path / "memory-file"
    wrong_type.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RuntimePathError, match="must be a directory"):
        discover_legacy_artifacts(paths, {"AURA_MEMORY_DIR": os.fspath(wrong_type)})


def test_legacy_discovery_rejects_inaccessible_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    candidate = tmp_path / "ego.json"
    candidate.touch()
    original_stat = Path.stat

    def denied_stat(path: Path, *args, **kwargs):
        # Python 3.12 implements Path.lstat() through stat(...,
        # follow_symlinks=False).  Let the symlink-safety probe succeed so
        # this test exercises the later population-classification stat call.
        if path == candidate and kwargs.get("follow_symlinks", True):
            raise PermissionError("metadata denied")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied_stat)
    with pytest.raises(RuntimePathError, match="cannot inspect legacy ego artifact"):
        discover_legacy_artifacts(paths, {"AURA_EGO_PATH": os.fspath(candidate)})


def test_legacy_symlink_aliases_deduplicate_to_one_target(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    target_root = tmp_path / "target-output"
    target = target_root / "chat_spool"
    _write_immediate_entry(target)
    alias_root = tmp_path / "alias-output"
    _make_symlink_or_skip(alias_root, target_root, directory=True)
    manifest = discover_legacy_artifacts(
        paths,
        {
            "AURA_OUTPUT_DIR": os.fspath(alias_root),
            "AURA_CHAT_SPOOL_DIR": os.fspath(target),
        },
    )
    candidates = manifest.candidates_for(LegacyArtifactKind.TRANSPORTS)
    assert candidates.count(target.resolve()) == 1
    assert LegacyArtifactKind.TRANSPORTS not in manifest.conflicts


def test_legacy_discovery_rejects_broken_symlink(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    broken = tmp_path / "broken-memory"
    _make_symlink_or_skip(broken, tmp_path / "missing-target", directory=True)
    with pytest.raises(RuntimePathError, match="invalid symlink"):
        discover_legacy_artifacts(paths, {"AURA_MEMORY_DIR": os.fspath(broken)})


def test_legacy_discovery_rejects_cyclic_symlink(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    cycle = tmp_path / "cycle-memory"
    _make_symlink_or_skip(cycle, cycle, directory=True)
    with pytest.raises(RuntimePathError, match="invalid symlink"):
        discover_legacy_artifacts(paths, {"AURA_MEMORY_DIR": os.fspath(cycle)})


def test_legacy_discovery_rejects_inaccessible_symlink_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_paths(tmp_path, cwd=tmp_path / "project")
    target = tmp_path / "memory-target"
    target.mkdir()
    link = tmp_path / "memory-link"
    _make_symlink_or_skip(link, target, directory=True)
    original_lstat = Path.lstat

    def denied_lstat(path: Path):
        if path == link:
            raise PermissionError("link metadata denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", denied_lstat)
    with pytest.raises(RuntimePathError, match="cannot inspect legacy artifact candidate"):
        discover_legacy_artifacts(paths, {"AURA_MEMORY_DIR": os.fspath(link)})


def test_fallback_symlink_alias_deduplicates_one_resolved_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise discovery without requiring Windows symlink privilege."""

    workspace = Path.cwd()
    paths = make_paths(workspace, cwd=workspace / "project")
    target = paths._base_dir / "outputs" / "ego_state.json"
    alias = workspace / "alias-ego"

    def fake_lstat(path: Path):
        mode = stat.S_IFLNK if path == alias else stat.S_IFDIR
        return SimpleNamespace(st_mode=mode)

    def fake_resolve(path: Path, strict: bool = False):
        return target if path == alias else path

    def fake_stat(path: Path, *args, **kwargs):
        if path == target:
            return SimpleNamespace(st_mode=stat.S_IFREG)
        raise FileNotFoundError(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    monkeypatch.setattr(Path, "stat", fake_stat)
    manifest = discover_legacy_artifacts(paths, {"AURA_EGO_PATH": os.fspath(alias)})
    assert manifest.candidates_for(LegacyArtifactKind.EGO) == (target,)
    assert manifest.populated_for(LegacyArtifactKind.EGO) == (target,)
    assert LegacyArtifactKind.EGO not in manifest.conflicts


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("broken"), "invalid symlink"),
        (RuntimeError("cycle"), "invalid symlink"),
        (PermissionError("denied"), "cannot inspect legacy artifact candidate"),
    ],
)
def test_fallback_symlink_failures_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    message: str,
) -> None:
    base_dir = Path.cwd()
    link = base_dir / "link"

    def fake_lstat(path: Path):
        if path == link and isinstance(failure, PermissionError):
            raise failure
        return SimpleNamespace(st_mode=stat.S_IFLNK if path == link else stat.S_IFDIR)

    def fake_resolve(path: Path, strict: bool = False):
        if path == link and strict:
            raise failure
        return path

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(RuntimePathError, match=message):
        _canonical_legacy_candidate(link, base_dir, label="fallback")


@pytest.mark.parametrize("failure", [FileNotFoundError("broken"), RuntimeError("cycle")])
def test_intermediate_link_before_parent_component_is_not_normalized_away(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    base = Path.cwd() / "fallback-base"
    link = base / "intermediate-link"
    lexical = _unresolved_absolute_path(
        Path("intermediate-link") / ".." / "artifact", base, label="legacy"
    )
    assert "intermediate-link" in lexical.parts
    assert ".." in lexical.parts

    def fake_lstat(path: Path):
        return SimpleNamespace(st_mode=stat.S_IFLNK if path == link else stat.S_IFDIR)

    def fake_resolve(path: Path, strict: bool = False):
        if path == link and strict:
            raise failure
        return path

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(RuntimePathError, match="invalid symlink"):
        _canonical_legacy_candidate(
            Path("intermediate-link") / ".." / "artifact", base, label="legacy"
        )


@pytest.mark.parametrize(
    ("lexical", "link_name", "failure"),
    [
        (Path("missing") / ".." / "broken-link" / "artifact", "broken-link", FileNotFoundError("broken")),
        (Path("missing") / ".." / "cyclic-link" / "artifact", "cyclic-link", RuntimeError("cycle")),
        (Path("missing") / "child" / ".." / ".." / "broken-link", "broken-link", FileNotFoundError("broken")),
    ],
)
def test_missing_prefix_parent_escape_still_validates_later_symlink(
    monkeypatch: pytest.MonkeyPatch,
    lexical: Path,
    link_name: str,
    failure: Exception,
) -> None:
    base = Path.cwd() / "missing-prefix-base"
    missing = base / "missing"
    link = base / link_name

    def fake_lstat(path: Path):
        if path == missing:
            raise FileNotFoundError("missing")
        return SimpleNamespace(st_mode=stat.S_IFLNK if path == link else stat.S_IFDIR)

    def fake_resolve(path: Path, strict: bool = False):
        if path == link and strict:
            raise failure
        return path

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(RuntimePathError, match="invalid symlink"):
        _canonical_legacy_candidate(lexical, base, label="legacy")


def test_missing_tail_without_parent_escape_remains_absent_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = Path.cwd() / "missing-tail-base"
    missing = base / "missing"

    def fake_lstat(path: Path):
        if path == missing:
            raise FileNotFoundError("missing")
        return SimpleNamespace(st_mode=stat.S_IFDIR)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", lambda path, strict=False: path)
    candidate = _canonical_legacy_candidate(
        Path("missing") / "child" / "artifact", base, label="legacy"
    )
    assert candidate == base / "missing" / "child" / "artifact"


def test_valid_link_parent_uses_resolved_target_parent_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = Path.cwd() / "valid-link-base"
    link = base / "valid-link"
    target = base / "target-parent" / "target-child"
    later = target.parent / "later"
    inspected: list[Path] = []

    def fake_lstat(path: Path):
        inspected.append(path)
        if path == link:
            return SimpleNamespace(st_mode=stat.S_IFLNK)
        if path == later:
            return SimpleNamespace(st_mode=stat.S_IFDIR)
        return SimpleNamespace(st_mode=stat.S_IFDIR)

    def fake_resolve(path: Path, strict: bool = False):
        return target if path == link else path

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    monkeypatch.setattr(
        Path, "stat", lambda path, *args, **kwargs: SimpleNamespace(st_mode=stat.S_IFDIR)
    )
    _canonical_legacy_candidate(Path("valid-link") / ".." / "later", base, label="legacy")
    assert later in inspected
    assert base / "later" not in inspected


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


def test_bootstrap_reports_single_populated_sources_in_kind_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path.cwd() / "legacy-report"
    empty = {kind: () for kind in LegacyArtifactKind}
    populated = dict(empty)
    populated[LegacyArtifactKind.IDENTITY] = (root / "identity.json",)
    populated[LegacyArtifactKind.TRANSPORTS] = (root / "chat-spool",)
    manifest = LegacyArtifactManifest(
        candidates=MappingProxyType(empty),
        populated=MappingProxyType(populated),
        conflicts=MappingProxyType({}),
    )
    _report_unpromoted_legacy_sources(manifest)
    assert capsys.readouterr().out.splitlines() == [
        f"Legacy identity source detected at {root / 'identity.json'} "
        "(not migrated or promoted).",
        f"Legacy transports source detected at {root / 'chat-spool'} "
        "(not migrated or promoted).",
    ]


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


def test_canonical_config_properties_do_not_trigger_legacy_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.runtime_paths as runtime_paths
    from config import Config

    calls: list[object] = []

    def inspected(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimePathError("inspection was requested")

    monkeypatch.setattr(runtime_paths, "discover_legacy_artifacts", inspected)
    assert isinstance(Config.RUNTIME_PATHS, RuntimePaths)
    assert Config.DATA_DIR
    assert Config.CONTROL_DB_PATH
    assert Config.WRITER_LEASE_PATH
    assert calls == []
    with pytest.raises(RuntimePathError, match="inspection was requested"):
        _ = Config.LEGACY_ARTIFACT_MANIFEST
    assert len(calls) == 1


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


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        sorted(
            (
                os.fspath(path.relative_to(root)),
                path.lstat().st_mode,
                path.lstat().st_size,
            )
            for path in root.rglob("*")
        )
    )


def _bootstrap_environment(**updates: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AURA_")
    }
    environment.update(updates)
    return environment


def _run_bootstrap(project_root: Path, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", os.fspath(project_root / "bootstrap.py")],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_bootstrap_invalid_root_exits_two_before_any_layout_write(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    before = _tree_snapshot(tmp_path)
    result = _run_bootstrap(
        project_root,
        tmp_path,
        _bootstrap_environment(AURA_DATA_DIR=os.fspath(Path(tmp_path.anchor))),
    )
    assert result.returncode == 2
    assert "Runtime layout validation failed" in result.stderr
    assert _tree_snapshot(tmp_path) == before


def test_bootstrap_real_conflict_exits_two_before_canonical_layout_write(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    canonical = tmp_path / "canonical-data"
    historical_root = tmp_path / "historical-output"
    override = tmp_path / "override-chat"
    _write_immediate_entry(historical_root / "chat_spool")
    _write_immediate_entry(override)
    before = _tree_snapshot(tmp_path)
    result = _run_bootstrap(
        project_root,
        tmp_path,
        _bootstrap_environment(
            AURA_DATA_DIR=os.fspath(canonical),
            AURA_OUTPUT_DIR=os.fspath(historical_root),
            AURA_CHAT_SPOOL_DIR=os.fspath(override),
        ),
    )
    assert result.returncode == 2
    assert "legacy artifact conflicts require migration" in result.stderr
    assert not canonical.exists()
    assert _tree_snapshot(tmp_path) == before


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
