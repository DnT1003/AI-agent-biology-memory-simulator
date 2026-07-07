"""
Download Claude native binaries (Artifactory / GCS).

Port of: src/utils/nativeInstaller/download.ts (API surface + constants).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

GCS_BUCKET_URL = (
    "https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/"
    "claude-code-releases"
)
ARTIFACTORY_REGISTRY_URL = "https://artifactory.infra.ant.dev/artifactory/api/npm/npm-all/"


async def get_latest_version_from_artifactory(tag: str = "latest") -> str:
    """Resolve npm dist-tag to semver (stub)."""
    del tag
    return os.environ.get("CLAUDE_CODE_VERSION", "0.0.0")


async def download_native_binary(
    _version: str,
    _dest_dir: Path,
    **_opts: Any,
) -> Path:
    raise NotImplementedError("Native binary download not wired in Python port")
