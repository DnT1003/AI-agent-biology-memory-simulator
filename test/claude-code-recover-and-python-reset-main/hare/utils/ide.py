"""IDE detection, lockfiles, extension install — port of `ide.ts` (wiring stubs)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hare.utils.jetbrains import is_jetbrains_plugin_installed_cached

IdeType = Literal[
    "cursor",
    "windsurf",
    "vscode",
    "pycharm",
    "intellij",
    "webstorm",
    "phpstorm",
    "rubymine",
    "clion",
    "goland",
    "rider",
    "datagrip",
    "appcode",
    "dataspell",
    "aqua",
    "gateway",
    "fleet",
    "androidstudio",
]


@dataclass
class IdeConfig:
    ide_kind: Literal["vscode", "jetbrains"]
    display_name: str
    process_keywords_mac: list[str]
    process_keywords_windows: list[str]
    process_keywords_linux: list[str]


SUPPORTED_IDE_CONFIGS: dict[str, IdeConfig] = {
    "cursor": IdeConfig("vscode", "Cursor", ["Cursor Helper", "Cursor.app"], ["cursor.exe"], ["cursor"]),
    "windsurf": IdeConfig("vscode", "Windsurf", ["Windsurf Helper", "Windsurf.app"], ["windsurf.exe"], ["windsurf"]),
    "vscode": IdeConfig("vscode", "VS Code", ["Visual Studio Code", "Code Helper"], ["code.exe"], ["code"]),
    "intellij": IdeConfig("jetbrains", "IntelliJ IDEA", ["IntelliJ IDEA"], ["idea64.exe"], ["idea", "intellij"]),
    "pycharm": IdeConfig("jetbrains", "PyCharm", ["PyCharm"], ["pycharm64.exe"], ["pycharm"]),
    "webstorm": IdeConfig("jetbrains", "WebStorm", ["WebStorm"], ["webstorm64.exe"], ["webstorm"]),
    "phpstorm": IdeConfig("jetbrains", "PhpStorm", ["PhpStorm"], ["phpstorm64.exe"], ["phpstorm"]),
    "rubymine": IdeConfig("jetbrains", "RubyMine", ["RubyMine"], ["rubymine64.exe"], ["rubymine"]),
    "clion": IdeConfig("jetbrains", "CLion", ["CLion"], ["clion64.exe"], ["clion"]),
    "goland": IdeConfig("jetbrains", "GoLand", ["GoLand"], ["goland64.exe"], ["goland"]),
    "rider": IdeConfig("jetbrains", "Rider", ["Rider"], ["rider64.exe"], ["rider"]),
    "datagrip": IdeConfig("jetbrains", "DataGrip", ["DataGrip"], ["datagrip64.exe"], ["datagrip"]),
    "appcode": IdeConfig("jetbrains", "AppCode", ["AppCode"], ["appcode.exe"], ["appcode"]),
    "dataspell": IdeConfig("jetbrains", "DataSpell", ["DataSpell"], ["dataspell64.exe"], ["dataspell"]),
    "aqua": IdeConfig("jetbrains", "Aqua", [], ["aqua64.exe"], []),
    "gateway": IdeConfig("jetbrains", "Gateway", [], ["gateway64.exe"], []),
    "fleet": IdeConfig("jetbrains", "Fleet", [], ["fleet.exe"], []),
    "androidstudio": IdeConfig("jetbrains", "Android Studio", ["Android Studio"], ["studio64.exe"], ["android-studio"]),
}


def is_vscode_ide(ide: str | None) -> bool:
    if not ide:
        return False
    c = SUPPORTED_IDE_CONFIGS.get(ide)
    return c.ide_kind == "vscode" if c else False


def is_jetbrains_ide(ide: str | None) -> bool:
    if not ide:
        return False
    c = SUPPORTED_IDE_CONFIGS.get(ide)
    return c.ide_kind == "jetbrains" if c else False


def to_ide_display_name(terminal: str | None) -> str:
    if not terminal:
        return "IDE"
    c = SUPPORTED_IDE_CONFIGS.get(terminal)
    if c:
        return c.display_name
    base = Path(terminal.split()[0]).name.lower() if terminal else ""
    names = {"code": "VS Code", "cursor": "Cursor", "windsurf": "Windsurf", "vim": "Vim", "nano": "nano"}
    return names.get(base, (base or terminal).capitalize())


@dataclass
class DetectedIdeInfo:
    name: str
    port: int
    workspace_folders: list[str]
    url: str
    is_valid: bool
    auth_token: str | None = None
    ide_running_in_windows: bool | None = None


async def get_sorted_ide_lockfiles() -> list[str]:
    """Return `.lock` paths newest first — stub."""
    return []


async def cleanup_stale_ide_lockfiles() -> None:
    return


async def detect_ides(include_invalid: bool) -> list[DetectedIdeInfo]:
    return []


async def find_available_ide() -> DetectedIdeInfo | None:
    return None


async def is_ide_extension_installed(ide_type: str) -> bool:
    if is_vscode_ide(ide_type):
        r = subprocess.run(["code", "--list-extensions"], capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and "anthropic.claude-code" in (r.stdout or "")
    if is_jetbrains_ide(ide_type):
        return await is_jetbrains_plugin_installed_cached(ide_type)
    return False


def get_connected_ide_client(_mcp_clients: list[Any]) -> Any:
    return None


def has_access_to_ide_extension_diff_feature(mcp_clients: list[Any]) -> bool:
    return any(getattr(c, "name", None) == "ide" for c in mcp_clients if getattr(c, "type", None) == "connected")


async def close_open_diffs(_ide_client: Any) -> None:
    return


CC_VERSION = "2.1.88"
