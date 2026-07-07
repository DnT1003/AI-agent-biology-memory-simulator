"""`claude doctor` installation diagnostics (`doctorDiagnostic.ts`). — stub."""

from __future__ import annotations

from typing import Any, Literal

InstallationType = Literal[
    "npm-global",
    "npm-local",
    "native",
    "package-manager",
    "development",
    "unknown",
]


async def get_current_installation_type() -> InstallationType:
    import os

    if os.environ.get("NODE_ENV") == "development":
        return "development"
    return "unknown"


async def get_doctor_diagnostic() -> dict[str, Any]:
    return {
        "installationType": await get_current_installation_type(),
        "version": "unknown",
        "installationPath": "",
        "invokedBinary": "",
        "configInstallMethod": "not set",
        "autoUpdates": "enabled",
        "hasUpdatePermissions": None,
        "multipleInstallations": [],
        "warnings": [],
        "ripgrepStatus": {"working": True, "mode": "embedded", "systemPath": None},
    }
