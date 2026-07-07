"""
Fast mode availability, org status prefetch, cooldown state.

Port of: src/utils/fastMode.ts — external services stubbed; see set_* hooks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

from hare.utils.debug import log_for_debugging
from hare.utils.env_utils import is_env_truthy

CooldownReason = Literal["rate_limit", "overloaded"]
FastModeDisabledReason = Literal[
    "free", "preference", "extra_usage_disabled", "network_error", "unknown"
]
FastModeRuntimeState = (
    dict[str, Literal["active"]] | dict[str, Any]
)  # {status: 'cooldown', resetAt, reason}

FAST_MODE_MODEL_DISPLAY = "Opus 4.6"

_get_feature_value_cached: Callable[[str, Any], Any] = lambda _k, d: d
_get_is_non_interactive: Callable[[], bool] = lambda: False
_get_kairos_active: Callable[[], bool] = lambda: False
_prefer_third_party_auth: Callable[[], bool] = lambda: False
_get_api_provider: Callable[[], str] = lambda: "firstParty"
_get_global_config: Callable[[], dict[str, Any]] = lambda: {}
_save_global_config: Callable[[Any], None] = lambda _f: None
_get_settings_for_source: Callable[[str], dict[str, Any] | None] = lambda _s: None
_update_settings_for_source: Callable[[str, dict[str, Any]], None] = lambda _s, _u: None
_get_claude_ai_oauth_tokens: Callable[[], Any] = lambda: None
_get_anthropic_api_key: Callable[[], str | None] = lambda: None
_has_profile_scope: Callable[[], bool] = lambda: True
_handle_oauth_401: Callable[[str], Any] = lambda _t: None
_is_essential_traffic_only: Callable[[], bool] = lambda: False
_is_in_bundled_mode: Callable[[], bool] = lambda: False
_log_event: Callable[[str, dict[str, Any]], None] = lambda _e, _m: None
_get_default_main_loop_model: Callable[[], str] = lambda: "opus"
_parse_user_specified_model: Callable[[str], str] = lambda m: m
_is_opus_1m_merge_enabled: Callable[[], bool] = lambda: False
_get_initial_settings: Callable[[], dict[str, Any]] = lambda: {}


def is_fast_mode_enabled() -> bool:
    return not is_env_truthy(os.environ.get("CLAUDE_CODE_DISABLE_FAST_MODE"))


def _disabled_reason_message(disabled_reason: str, auth_type: str) -> str:
    if disabled_reason == "free":
        return (
            "Fast mode requires a paid subscription"
            if auth_type == "oauth"
            else "Fast mode unavailable during evaluation. Please purchase credits."
        )
    if disabled_reason == "preference":
        return "Fast mode has been disabled by your organization"
    if disabled_reason == "extra_usage_disabled":
        return "Fast mode requires extra usage billing · /extra-usage to enable"
    if disabled_reason == "network_error":
        return "Fast mode unavailable due to network connectivity issues"
    return "Fast mode is currently unavailable"


def get_fast_mode_unavailable_reason() -> str | None:
    if not is_fast_mode_enabled():
        return "Fast mode is not available"
    r = _get_feature_value_cached("tengu_penguins_off", None)
    if r is not None:
        log_for_debugging(f"Fast mode unavailable: {r}")
        return str(r)
    if not _is_in_bundled_mode() and _get_feature_value_cached(
        "tengu_marble_sandcastle", False
    ):
        return "Fast mode requires the native binary · Install from: https://claude.com/product/claude-code"
    if (
        _get_is_non_interactive()
        and _prefer_third_party_auth()
        and not _get_kairos_active()
    ):
        if not (_get_settings_for_source("flagSettings") or {}).get("fastMode"):
            reason = "Fast mode is not available in the Agent SDK"
            log_for_debugging(f"Fast mode unavailable: {reason}")
            return reason
    if _get_api_provider() != "firstParty":
        reason = "Fast mode is not available on Bedrock, Vertex, or Foundry"
        log_for_debugging(f"Fast mode unavailable: {reason}")
        return reason
    if _org_status["status"] == "disabled":
        reason_d = _org_status.get("reason") or "unknown"
        if reason_d in ("network_error", "unknown") and is_env_truthy(
            os.environ.get("CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS")
        ):
            return None
        auth_type = "oauth" if _get_claude_ai_oauth_tokens() else "api-key"
        msg = _disabled_reason_message(reason_d, auth_type)  # type: ignore[arg-type]
        log_for_debugging(f"Fast mode unavailable: {msg}")
        return msg
    return None


def is_fast_mode_available() -> bool:
    if not is_fast_mode_enabled():
        return False
    return get_fast_mode_unavailable_reason() is None


def get_fast_mode_model() -> str:
    return "opus" + ("[1m]" if _is_opus_1m_merge_enabled() else "")


def is_fast_mode_supported_by_model(model_setting: str | None) -> bool:
    if not is_fast_mode_enabled():
        return False
    model = model_setting or _get_default_main_loop_model()
    parsed = _parse_user_specified_model(model)
    return "opus-4-6" in parsed.lower()


def get_initial_fast_mode_setting(model: str) -> bool:
    if not is_fast_mode_enabled() or get_fast_mode_unavailable_reason() is not None:
        return False
    if not is_fast_mode_supported_by_model(model):
        return False
    settings = _get_initial_settings()
    if settings.get("fastModePerSessionOptIn"):
        return False
    return settings.get("fastMode") is True


_runtime_state: dict[str, Any] = {"status": "active"}
_has_logged_cooldown_expiry = False


class _Pub:
    def __init__(self) -> None:
        self._subs: list[Callable[..., Any]] = []

    def subscribe(self, fn: Callable[..., Any]) -> Callable[[], None]:
        self._subs.append(fn)

        def unsub() -> None:
            if fn in self._subs:
                self._subs.remove(fn)

        return unsub

    def emit(self, *a: Any, **k: Any) -> None:
        for fn in self._subs:
            fn(*a, **k)


_cooldown_triggered = _Pub()
_cooldown_expired = _Pub()
on_cooldown_triggered = _cooldown_triggered.subscribe
on_cooldown_expired = _cooldown_expired.subscribe


def get_fast_mode_runtime_state() -> FastModeRuntimeState:
    global _runtime_state, _has_logged_cooldown_expiry
    if (
        _runtime_state.get("status") == "cooldown"
        and __import__("time").time() * 1000 >= _runtime_state.get("resetAt", 0)
    ):
        if is_fast_mode_enabled() and not _has_logged_cooldown_expiry:
            log_for_debugging("Fast mode cooldown expired, re-enabling fast mode")
            _has_logged_cooldown_expiry = True
            _cooldown_expired.emit()
        _runtime_state = {"status": "active"}
    return _runtime_state  # type: ignore[return-value]


def trigger_fast_mode_cooldown(reset_timestamp_ms: float, reason: CooldownReason) -> None:
    global _runtime_state, _has_logged_cooldown_expiry
    if not is_fast_mode_enabled():
        return
    _runtime_state = {"status": "cooldown", "resetAt": reset_timestamp_ms, "reason": reason}
    _has_logged_cooldown_expiry = False
    import time

    dur = reset_timestamp_ms - time.time() * 1000
    log_for_debugging(
        f"Fast mode cooldown triggered ({reason}), duration {round(dur / 1000)}s"
    )
    _log_event(
        "tengu_fast_mode_fallback_triggered",
        {"cooldown_duration_ms": dur, "cooldown_reason": reason},
    )
    _cooldown_triggered.emit(reset_timestamp_ms, reason)


def clear_fast_mode_cooldown() -> None:
    global _runtime_state
    _runtime_state = {"status": "active"}


def handle_fast_mode_rejected_by_api() -> None:
    global _org_status
    if _org_status["status"] == "disabled":
        return
    _org_status = {"status": "disabled", "reason": "preference"}
    _update_settings_for_source("userSettings", {"fastMode": None})
    _save_global_config(
        lambda c: {**c, "penguinModeOrgEnabled": False}
        if isinstance(c, dict)
        else c
    )
    _org_fast_mode_change.emit(False)


_overage_rejection = _Pub()
on_fast_mode_overage_rejection = _overage_rejection.subscribe


def _overage_disabled_message(reason: str | None) -> str:
    m = {
        "out_of_credits": "Fast mode disabled · extra usage credits exhausted",
        "org_level_disabled": "Fast mode disabled · extra usage disabled by your organization",
        "org_service_level_disabled": "Fast mode disabled · extra usage disabled by your organization",
        "org_level_disabled_until": "Fast mode disabled · extra usage spending cap reached",
        "member_level_disabled": "Fast mode disabled · extra usage disabled for your account",
        "seat_tier_level_disabled": "Fast mode disabled · extra usage not available for your plan",
        "seat_tier_zero_credit_limit": "Fast mode disabled · extra usage not available for your plan",
        "member_zero_credit_limit": "Fast mode disabled · extra usage not available for your plan",
        "overage_not_provisioned": "Fast mode requires extra usage billing · /extra-usage to enable",
        "no_limits_configured": "Fast mode requires extra usage billing · /extra-usage to enable",
    }
    return m.get(reason or "", "Fast mode disabled · extra usage not available")


def handle_fast_mode_overage_rejection(reason: str | None) -> None:
    message = _overage_disabled_message(reason)
    log_for_debugging(f"Fast mode overage rejection: {reason} — {message}")
    _log_event("tengu_fast_mode_overage_rejected", {"overage_disabled_reason": reason or "unknown"})
    if reason not in ("org_level_disabled_until", "out_of_credits"):
        _update_settings_for_source("userSettings", {"fastMode": None})
        _save_global_config(
            lambda c: {**c, "penguinModeOrgEnabled": False}
            if isinstance(c, dict)
            else c
        )
    _overage_rejection.emit(message)


def is_fast_mode_cooldown() -> bool:
    return get_fast_mode_runtime_state().get("status") == "cooldown"  # type: ignore[union-attr]


def get_fast_mode_state(model: str, fast_mode_user_enabled: bool | None) -> str:
    enabled = (
        is_fast_mode_enabled()
        and get_fast_mode_unavailable_reason() is None
        and bool(fast_mode_user_enabled)
        and is_fast_mode_supported_by_model(model)
    )
    if enabled and is_fast_mode_cooldown():
        return "cooldown"
    if enabled:
        return "on"
    return "off"


_org_status: dict[str, Any] = {"status": "pending"}
_org_fast_mode_change = _Pub()
on_org_fast_mode_changed = _org_fast_mode_change.subscribe

_PREFETCH_MIN_INTERVAL_MS = 30_000
_last_prefetch_at = 0.0
_inflight_prefetch: Any = None


def resolve_fast_mode_status_from_cache() -> None:
    global _org_status
    if not is_fast_mode_enabled():
        return
    if _org_status["status"] != "pending":
        return
    is_ant = os.environ.get("USER_TYPE") == "ant"
    cached = _get_global_config().get("penguinModeOrgEnabled") is True
    _org_status = (
        {"status": "enabled"} if is_ant or cached else {"status": "disabled", "reason": "unknown"}
    )


async def prefetch_fast_mode_status() -> None:
    global _last_prefetch_at, _inflight_prefetch, _org_status
    if _is_essential_traffic_only():
        return
    if not is_fast_mode_enabled():
        return
    # Stub: real implementation performs HTTP to Claude API
    resolve_fast_mode_status_from_cache()
