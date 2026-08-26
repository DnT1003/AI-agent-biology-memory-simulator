"""Contracts for the repository QA entry points; no nested pytest invocation."""

from __future__ import annotations

from configparser import ConfigParser
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _pytest_settings() -> dict[str, str]:
    parser = ConfigParser()
    loaded = parser.read(REPOSITORY_ROOT / "pytest.ini", encoding="utf-8")
    assert loaded == [str(REPOSITORY_ROOT / "pytest.ini")]
    return dict(parser["pytest"])


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
