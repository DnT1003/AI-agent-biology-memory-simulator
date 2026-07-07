"""Port of: src/utils/claudeInChrome/setup.ts + setupPortable.ts"""
from __future__ import annotations
import json, os, sys

def get_native_host_manifest_path() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome/NativeMessagingHosts")
    elif sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data", "NativeMessagingHosts")
    return os.path.expanduser("~/.config/google-chrome/NativeMessagingHosts")

async def setup_chrome_native_host() -> bool:
    """Setup Chrome native messaging host. Stub."""
    return False
