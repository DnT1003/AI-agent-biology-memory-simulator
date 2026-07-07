"""Apply settings.env to process environment — port of `managedEnv.ts`."""

from __future__ import annotations

import os
from typing import Any, Callable

from hare.utils.env_utils import is_env_truthy
from hare.utils.managed_env_constants import SAFE_ENV_VARS, is_provider_managed_env_var

_ccd_spawn_keys: set[str] | None | bool = False


def _without_ssh_tunnel_vars(env: dict[str, str] | None) -> dict[str, str]:
    if not env or not os.environ.get("ANTHROPIC_UNIX_SOCKET"):
        return dict(env or {})
    drop = {
        "ANTHROPIC_UNIX_SOCKET",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }
    return {k: v for k, v in env.items() if k not in drop}


def _without_host_managed_provider_vars(env: dict[str, str] | None) -> dict[str, str]:
    if not env:
        return {}
    if not is_env_truthy(os.environ.get("CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST")):
        return dict(env)
    return {k: v for k, v in env.items() if not is_provider_managed_env_var(k)}


def _without_ccd_spawn_keys(env: dict[str, str] | None) -> dict[str, str]:
    global _ccd_spawn_keys
    if not env or not isinstance(_ccd_spawn_keys, set):
        return dict(env or {})
    return {k: v for k, v in env.items() if k not in _ccd_spawn_keys}


def _filter_settings_env(env: dict[str, str] | None) -> dict[str, str]:
    return _without_ccd_spawn_keys(_without_host_managed_provider_vars(_without_ssh_tunnel_vars(env)))


def apply_safe_config_environment_variables() -> None:
    global _ccd_spawn_keys
    if _ccd_spawn_keys is False:
        _ccd_spawn_keys = (
            set(os.environ.keys()) if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop" else None
        )

    try:
        from hare.utils.config_full import get_global_config, get_settings_deprecated, get_settings_for_source  # type: ignore[import-not-found]
        from hare.utils.settings.constants import is_setting_source_enabled  # type: ignore[import-not-found]
    except ImportError:

        def get_global_config() -> Any:
            return type("G", (), {"env": {}})()

        def get_settings_deprecated() -> Any:
            return None

        def get_settings_for_source(_s: str) -> Any:
            return None

        def is_setting_source_enabled(_s: str) -> bool:
            return True

    for k, v in _filter_settings_env(getattr(get_global_config(), "env", None) or {}).items():
        os.environ[k] = v

    for source in ("userSettings", "flagSettings"):
        if not is_setting_source_enabled(source):
            continue
        s = get_settings_for_source(source)
        env = getattr(s, "env", None) if s else None
        for k, v in _filter_settings_env(env or {}).items():
            os.environ[k] = v

    try:
        from hare.services.remote_managed_settings.sync_cache import is_remote_managed_settings_eligible  # type: ignore[import-not-found]

        is_remote_managed_settings_eligible()
    except ImportError:
        pass

    pol = get_settings_for_source("policySettings")
    if pol:
        for k, v in _filter_settings_env(getattr(pol, "env", None) or {}).items():
            os.environ[k] = v

    merged = get_settings_deprecated()
    env = getattr(merged, "env", None) if merged else None
    for k, v in _filter_settings_env(env or {}).items():
        if k.upper() in SAFE_ENV_VARS:
            os.environ[k] = str(v)


def apply_config_environment_variables() -> None:
    try:
        from hare.utils.config_full import get_global_config, get_settings_deprecated  # type: ignore[import-not-found]
    except ImportError:
        return
    for k, v in _filter_settings_env(getattr(get_global_config(), "env", None) or {}).items():
        os.environ[k] = v
    merged = get_settings_deprecated()
    if merged:
        for k, v in _filter_settings_env(getattr(merged, "env", None) or {}).items():
            os.environ[k] = v
    for fn in (
        "hare.utils.ca_certs.clear_ca_certs_cache",
        "hare.utils.mtls.clear_mtls_cache",
        "hare.utils.proxy.clear_proxy_cache",
    ):
        try:
            __import__(fn.rsplit(".", 1)[0], fromlist=[fn.split(".")[-1]])
        except ImportError:
            pass
