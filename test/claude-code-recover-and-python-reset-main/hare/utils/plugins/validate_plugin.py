"""Validate plugin.json / marketplace manifests. Port of: src/utils/plugins/validatePlugin.ts"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass
class ValidationError:
    path: str
    message: str
    code: str | None = None


@dataclass
class ValidationWarning:
    path: str
    message: str


@dataclass
class ValidationResult:
    success: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)
    file_path: str = ""
    file_type: Literal["plugin", "marketplace", "skill", "agent", "command", "hooks"] = "plugin"


async def validate_plugin_file(path: str | Path) -> ValidationResult:
    """Run zod-equivalent validation (stub)."""
    p = Path(path)
    if not p.is_file():
        return ValidationResult(
            success=False,
            errors=[ValidationError(path="root", message="File not found")],
            file_path=str(p),
        )
    return ValidationResult(success=True, file_path=str(p), file_type="plugin")
