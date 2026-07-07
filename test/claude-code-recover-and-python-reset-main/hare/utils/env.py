"""
Process and runtime environment probes for analytics and UX.

Port of: src/utils/env.ts
"""

from __future__ import annotations

import os
import platform
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

import urllib.request

from hare.utils.env_utils import get_claude_config_home_dir, is_env_truthy
from hare.utils.find_executable import find_executable


PlatformName = Literal["win32", "darwin", "linux"]


def _file_suffix_for_oauth_config() -> str:
    """Build-time OAuth filename suffix; stub empty."""
    return os.environ.get("CLAUDE_OAUTH_CONFIG_SUFFIX", "")


@lru_cache(maxsize=1)
def get_global_claude_file() -> str:
    legacy = Path(get_claude_config_home_dir()) / ".config.json"
    if legacy.is_file():
        return str(legacy)
    filename = f".claude{_file_suffix_for_oauth_config()}.json"
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home())
    return str(Path(base) / filename)


@lru_cache(maxsize=1)
def _has_internet_access_cached() -> bool:
    try:
        req = urllib.request.Request("http://1.1.1.1", method="HEAD")
        with urllib.request.urlopen(req, timeout=1.0) as r:
            return r.status < 500
    except OSError:
        return False


async def has_internet_access() -> bool:
    import asyncio

    return await asyncio.to_thread(_has_internet_access_cached)


def _is_command_available_sync(command: str) -> bool:
    from hare.utils.which import which_sync

    return which_sync(command) is not None


@lru_cache(maxsize=1)
def _detect_package_managers_sync() -> tuple[str, ...]:
    out: list[str] = []
    for name in ("npm", "yarn", "pnpm"):
        if _is_command_available_sync(name):
            out.append(name)
    return tuple(out)


@lru_cache(maxsize=1)
def _detect_runtimes_sync() -> tuple[str, ...]:
    out: list[str] = []
    for name in ("bun", "deno", "node"):
        if _is_command_available_sync(name):
            out.append(name)
    return tuple(out)


def _is_wsl_environment() -> bool:
    try:
        return Path("/proc/sys/fs/binfmt_misc/WSLInterop").is_file()
    except OSError:
        return False


@lru_cache(maxsize=1)
def _is_npm_from_windows_path() -> bool:
    if not _is_wsl_environment():
        return False
    try:
        cmd = find_executable("npm", [])["cmd"]
        return str(cmd).startswith("/mnt/c/")
    except OSError:
        return False


def _is_conductor() -> bool:
    return os.environ.get("__CFBundleIdentifier") == "com.conductor.app"


JETBRAINS_IDES = (
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
    "jetbrains",
    "androidstudio",
)


def _is_ssh_session() -> bool:
    return bool(
        os.environ.get("SSH_CONNECTION")
        or os.environ.get("SSH_CLIENT")
        or os.environ.get("SSH_TTY")
    )


def detect_terminal() -> str | None:
    if os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    ask = os.environ.get("VSCODE_GIT_ASKPASS_MAIN") or ""
    if "cursor" in ask:
        return "cursor"
    if "windsurf" in ask:
        return "windsurf"
    if "antigravity" in ask:
        return "antigravity"
    bundle = (os.environ.get("__CFBundleIdentifier") or "").lower()
    if "vscodium" in bundle:
        return "codium"
    if "windsurf" in bundle:
        return "windsurf"
    if "com.google.android.studio" in bundle:
        return "androidstudio"
    if bundle:
        for ide in JETBRAINS_IDES:
            if ide in bundle:
                return ide
    if os.environ.get("VisualStudioVersion"):
        return "visualstudio"
    if os.environ.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        return "pycharm"
    if os.environ.get("TERM") == "xterm-ghostty":
        return "ghostty"
    term = os.environ.get("TERM") or ""
    if "kitty" in term:
        return "kitty"
    if os.environ.get("TERM_PROGRAM"):
        return os.environ["TERM_PROGRAM"]
    if os.environ.get("TMUX"):
        return "tmux"
    if os.environ.get("STY"):
        return "screen"
    if os.environ.get("KONSOLE_VERSION"):
        return "konsole"
    if os.environ.get("GNOME_TERMINAL_SERVICE"):
        return "gnome-terminal"
    if os.environ.get("XTERM_VERSION"):
        return "xterm"
    if os.environ.get("VTE_VERSION"):
        return "vte-based"
    if os.environ.get("TERMINATOR_UUID"):
        return "terminator"
    if os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"
    if os.environ.get("ALACRITTY_LOG"):
        return "alacritty"
    if os.environ.get("TILIX_ID"):
        return "tilix"
    if os.environ.get("WT_SESSION"):
        return "windows-terminal"
    if os.environ.get("SESSIONNAME") and os.environ.get("TERM") == "cygwin":
        return "cygwin"
    if os.environ.get("MSYSTEM"):
        return os.environ["MSYSTEM"].lower()
    if os.environ.get("ConEmuANSI") or os.environ.get("ConEmuPID") or os.environ.get("ConEmuTask"):
        return "conemu"
    if os.environ.get("WSL_DISTRO_NAME"):
        return f"wsl-{os.environ['WSL_DISTRO_NAME']}"
    if _is_ssh_session():
        return "ssh-session"
    if os.environ.get("TERM"):
        t = os.environ["TERM"]
        if "alacritty" in t:
            return "alacritty"
        if "rxvt" in t:
            return "rxvt"
        if "termite" in t:
            return "termite"
        return t
    if not sys.stdout.isatty():
        return "non-interactive"
    return None


@lru_cache(maxsize=1)
def detect_deployment_environment() -> str:
    if is_env_truthy(os.environ.get("CODESPACES")):
        return "codespaces"
    if os.environ.get("GITPOD_WORKSPACE_ID"):
        return "gitpod"
    if os.environ.get("REPL_ID") or os.environ.get("REPL_SLUG"):
        return "replit"
    if os.environ.get("PROJECT_DOMAIN"):
        return "glitch"
    if is_env_truthy(os.environ.get("VERCEL")):
        return "vercel"
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_SERVICE_NAME"):
        return "railway"
    if is_env_truthy(os.environ.get("RENDER")):
        return "render"
    if is_env_truthy(os.environ.get("NETLIFY")):
        return "netlify"
    if os.environ.get("DYNO"):
        return "heroku"
    if os.environ.get("FLY_APP_NAME") or os.environ.get("FLY_MACHINE_ID"):
        return "fly.io"
    if is_env_truthy(os.environ.get("CF_PAGES")):
        return "cloudflare-pages"
    if os.environ.get("DENO_DEPLOYMENT_ID"):
        return "deno-deploy"
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return "aws-lambda"
    if os.environ.get("AWS_EXECUTION_ENV") == "AWS_ECS_FARGATE":
        return "aws-fargate"
    if os.environ.get("AWS_EXECUTION_ENV") == "AWS_ECS_EC2":
        return "aws-ecs"
    try:
        uuid_path = Path("/sys/hypervisor/uuid")
        if uuid_path.is_file():
            u = uuid_path.read_text(encoding="utf-8").strip().lower()
            if u.startswith("ec2"):
                return "aws-ec2"
    except OSError:
        pass
    if os.environ.get("K_SERVICE"):
        return "gcp-cloud-run"
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return "gcp"
    if os.environ.get("WEBSITE_SITE_NAME") or os.environ.get("WEBSITE_SKU"):
        return "azure-app-service"
    if os.environ.get("AZURE_FUNCTIONS_ENVIRONMENT"):
        return "azure-functions"
    app_url = os.environ.get("APP_URL") or ""
    if "ondigitalocean.app" in app_url:
        return "digitalocean-app-platform"
    if os.environ.get("SPACE_CREATOR_USER_ID"):
        return "huggingface-spaces"
    if is_env_truthy(os.environ.get("GITHUB_ACTIONS")):
        return "github-actions"
    if is_env_truthy(os.environ.get("GITLAB_CI")):
        return "gitlab-ci"
    if os.environ.get("CIRCLECI"):
        return "circleci"
    if os.environ.get("BUILDKITE"):
        return "buildkite"
    if is_env_truthy(os.environ.get("CI")):
        return "ci"
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    try:
        if Path("/.dockerenv").is_file():
            return "docker"
    except OSError:
        pass
    plat = _normalized_platform()
    if plat == "darwin":
        return "unknown-darwin"
    if plat == "linux":
        return "unknown-linux"
    if plat == "win32":
        return "unknown-win32"
    return "unknown"


def _normalized_platform() -> PlatformName:
    p = sys.platform
    if p in ("win32", "darwin"):
        return p  # type: ignore[return-value]
    return "linux"


@runtime_checkable
class _BundledMode(Protocol):
    def is_running_with_bun(self) -> bool: ...


_bundled: _BundledMode | None = None


def set_bundled_mode_provider(provider: _BundledMode | None) -> None:
    global _bundled
    _bundled = provider


def _is_running_with_bun() -> bool:
    if _bundled:
        return _bundled.is_running_with_bun()
    return False


_host_arch: str = platform.machine() or ""


class EnvNamespace:
    has_internet_access = staticmethod(has_internet_access)
    is_ci = is_env_truthy(os.environ.get("CI"))
    platform: PlatformName = _normalized_platform()
    arch: str = _host_arch
    node_version: str = sys.version
    terminal: str | None = detect_terminal()
    is_ssh = staticmethod(_is_ssh_session)
    get_package_managers = staticmethod(lambda: list(_detect_package_managers_sync()))
    get_runtimes = staticmethod(lambda: list(_detect_runtimes_sync()))
    is_running_with_bun = staticmethod(_is_running_with_bun)
    is_wsl_environment = staticmethod(_is_wsl_environment)
    is_npm_from_windows_path = staticmethod(_is_npm_from_windows_path)
    is_conductor = staticmethod(_is_conductor)
    detect_deployment_environment = staticmethod(detect_deployment_environment)


env = EnvNamespace()


def get_host_platform_for_analytics() -> PlatformName:
    override = os.environ.get("CLAUDE_CODE_HOST_PLATFORM")
    if override in ("win32", "darwin", "linux"):
        return override  # type: ignore[return-value]
    return env.platform
