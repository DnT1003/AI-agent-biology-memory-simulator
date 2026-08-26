"""Contracts for the repository QA entry points; no nested pytest invocation."""

from __future__ import annotations

from configparser import ConfigParser
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
QA_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "qa.yml"

KNOWN_FLAKE_001 = (
    "tests/test_operation_ledger_m3.py::OperationLedgerTests::"
    "test_purge_removes_old_terminal_rows_but_never_active_rows"
)
KNOWN_FLAKE_002 = (
    "tests/test_dream_operation_ledger_m3.py::DreamOperationLedgerTests::"
    "test_bad_pending_operation_does_not_starve_next_valid_plan"
)


def _pytest_settings() -> dict[str, str]:
    parser = ConfigParser()
    loaded = parser.read(REPOSITORY_ROOT / "pytest.ini", encoding="utf-8")
    assert loaded == [str(REPOSITORY_ROOT / "pytest.ini")]
    return dict(parser["pytest"])


def _qa_workflow_step_lines(name: str) -> list[str]:
    """Return workflow step source lines without parsing or executing YAML."""
    lines = QA_WORKFLOW.read_text(encoding="utf-8").splitlines()
    step_start = lines.index(f"      - name: {name}")
    step_end = next(
        (
            index
            for index in range(step_start + 1, len(lines))
            if lines[index].startswith("      - name: ")
        ),
        len(lines),
    )
    return lines[step_start:step_end]


def _qa_workflow_step_command(name: str) -> str:
    """Return a folded ``run: >-`` command by source inspection only."""
    step = _qa_workflow_step_lines(name)
    run_start = step.index("        run: >-")
    return " ".join(line.strip() for line in step[run_start + 1 :] if line.startswith("          "))


def test_pytest_discovery_is_limited_to_the_repository_tests_tree() -> None:
    settings = _pytest_settings()

    assert settings["testpaths"].split() == ["tests"]
    assert settings["python_files"].split() == ["test_*.py"]
    assert "--ignore=scripts/test_generation.py" in settings["addopts"].split()


def test_pytest_does_not_recurse_into_unrelated_or_generated_trees() -> None:
    excluded = set(_pytest_settings()["norecursedirs"].split())

    assert {
        "test",
        "scripts",
        ".venv",
        ".venv_aura",
        ".venv-aura-qa",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".pyright",
        ".git",
        ".agents",
        ".codex",
    } <= excluded


def test_pinned_qa_tools_match_the_verified_baseline() -> None:
    requirements = (REPOSITORY_ROOT / "requirements-qa.txt").read_text(encoding="utf-8")

    assert "pytest==8.4.2" in requirements.splitlines()
    assert "pyright==1.1.411" in requirements.splitlines()


def test_pyright_checks_only_production_scope_at_python_312_basic_level() -> None:
    configuration = json.loads(
        (REPOSITORY_ROOT / "pyrightconfig.json").read_text(encoding="utf-8")
    )

    assert configuration["pythonVersion"] == "3.12"
    assert configuration["typeCheckingMode"] == "basic"
    assert {"core", "components", "dashboard"} <= set(configuration["include"])
    assert not {"tests", "test", "scripts"} & set(configuration["include"])
    assert {
        "tests",
        "test",
        "scripts",
        ".venv",
        ".venv_aura",
        ".venv-aura-qa",
        "venv",
        "env",
        "vendor",
        "reference",
        "references",
    } <= set(configuration["exclude"])
    assert not any(key.startswith("report") for key in configuration)


def test_a3_owned_known_flake_quarantines_use_only_exact_nodes() -> None:
    """A3 owns removal after insertion-order coverage and the Windows stability gate."""
    workflow = QA_WORKFLOW.read_text(encoding="utf-8")
    blocking_command = _qa_workflow_step_command(
        "Run suite excluding KNOWN-FLAKE-001 and KNOWN-FLAKE-002"
    )
    blocking_tokens = blocking_command.split()

    assert {
        f"--deselect={KNOWN_FLAKE_001}",
        f"--deselect={KNOWN_FLAKE_002}",
    } == {token for token in blocking_tokens if token.startswith("--deselect=")}
    assert "A3 owns removal" in workflow
    assert "same-time/clock-rollback insertion-order regression" in workflow
    assert "50 consecutive Windows passes" in workflow
    assert "after removing only its deselection" in workflow

    for diagnostic_name, known_flake in (
        ("KNOWN-FLAKE-001 diagnostic (non-blocking)", KNOWN_FLAKE_001),
        ("KNOWN-FLAKE-002 diagnostic (non-blocking)", KNOWN_FLAKE_002),
    ):
        diagnostic_step = _qa_workflow_step_lines(diagnostic_name)
        diagnostic_command = _qa_workflow_step_command(diagnostic_name)
        assert "        continue-on-error: true" in diagnostic_step
        assert diagnostic_command.split() == ["python", "-m", "pytest", known_flake, "-q"]


def test_qa_workflow_rejects_broad_known_flake_quarantine_mechanisms() -> None:
    """A3's temporary quarantine must never become a file, directory, or glob skip."""
    workflow = QA_WORKFLOW.read_text(encoding="utf-8")
    tokens = workflow.split()

    assert "--deselect" not in tokens
    assert {
        f"--deselect={KNOWN_FLAKE_001}",
        f"--deselect={KNOWN_FLAKE_002}",
    } == {token for token in tokens if token.startswith("--deselect=")}
    assert not any(token.startswith("--ignore") for token in tokens)
    assert "-k" not in tokens
    assert not any(token.startswith("-k") for token in tokens)
    assert not any(
        any(character in token for character in "*?[]")
        for token in tokens
        if token.startswith("tests/") or token.startswith("--deselect=tests/")
    )
