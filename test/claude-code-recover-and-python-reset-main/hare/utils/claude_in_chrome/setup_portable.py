"""Portable Chrome native-messaging setup (bundled extension).

Port of: src/utils/claudeInChrome/setupPortable.ts
"""

from __future__ import annotations

from pathlib import Path


def install_portable_native_host(_manifest_dir: Path) -> bool:
    return False
