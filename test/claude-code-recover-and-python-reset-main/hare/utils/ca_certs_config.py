"""Populate `NODE_EXTRA_CA_CERTS` from user settings (`caCertsConfig.ts`)."""

from __future__ import annotations

import os

from hare.utils.debug import log_for_debugging


def _get_extra_certs_path_from_config() -> str | None:
    try:
        from hare.utils.config import get_global_config
        from hare.utils.settings.settings import get_settings_for_source

        global_config = get_global_config()
        global_env = getattr(global_config, "env", None) if global_config else None
        settings = get_settings_for_source("userSettings")
        settings_env = getattr(settings, "env", None) if settings else None

        g_keys = ", ".join(global_env.keys()) if isinstance(global_env, dict) else "none"
        s_keys = ", ".join(settings_env.keys()) if isinstance(settings_env, dict) else "none"
        log_for_debugging(f"CA certs: Config fallback - globalEnv keys: {g_keys}, settingsEnv keys: {s_keys}")

        path = None
        if isinstance(settings_env, dict):
            path = settings_env.get("NODE_EXTRA_CA_CERTS") or path
        if isinstance(global_env, dict):
            path = path or global_env.get("NODE_EXTRA_CA_CERTS")
        if path:
            log_for_debugging(f"CA certs: Found NODE_EXTRA_CA_CERTS in config/settings: {path}")
        return path
    except Exception as e:  # noqa: BLE001
        log_for_debugging(f"CA certs: Config fallback failed: {e}", level="error")
        return None


def apply_extra_ca_certs_from_config() -> None:
    if os.environ.get("NODE_EXTRA_CA_CERTS"):
        return
    config_path = _get_extra_certs_path_from_config()
    if config_path:
        os.environ["NODE_EXTRA_CA_CERTS"] = config_path
        log_for_debugging(
            f"CA certs: Applied NODE_EXTRA_CA_CERTS from config to process.env: {config_path}",
        )
