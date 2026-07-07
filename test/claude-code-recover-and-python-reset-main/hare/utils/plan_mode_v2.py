"""
Plan mode v2 agent counts and feature gates. Port of src/utils/planModeV2.ts.
"""

from __future__ import annotations

import os
from typing import Literal

from hare.utils.auth import get_subscription_type
from hare.utils.env_utils import is_env_defined_falsy, is_env_truthy


def _get_rate_limit_tier() -> str | None:
    """Stub until auth exposes rate-limit tier (see TS getRateLimitTier)."""
    return None

PewterLedgerVariant = Literal["trim", "cut", "cap"] | None


def get_plan_mode_v2_agent_count() -> int:
    raw = os.environ.get("CLAUDE_CODE_PLAN_V2_AGENT_COUNT")
    if raw:
        try:
            count = int(raw, 10)
            if 0 < count <= 10:
                return count
        except ValueError:
            pass
    sub = get_subscription_type() or ""
    tier = _get_rate_limit_tier() or ""
    if sub == "max" and tier == "default_claude_max_20x":
        return 3
    if sub in ("enterprise", "team"):
        return 3
    return 1


def get_plan_mode_v2_explore_agent_count() -> int:
    raw = os.environ.get("CLAUDE_CODE_PLAN_V2_EXPLORE_AGENT_COUNT")
    if raw:
        try:
            count = int(raw, 10)
            if 0 < count <= 10:
                return count
        except ValueError:
            pass
    return 3


def is_plan_mode_interview_phase_enabled() -> bool:
    if os.environ.get("USER_TYPE") == "ant":
        return True
    env = os.environ.get("CLAUDE_CODE_PLAN_MODE_INTERVIEW_PHASE")
    if is_env_truthy(env):
        return True
    if is_env_defined_falsy(env):
        return False
    try:
        from hare.services.analytics.growthbook import get_feature_value_cached_may_be_stale

        return bool(get_feature_value_cached_may_be_stale("tengu_plan_mode_interview_phase", False))
    except ImportError:
        return False


def get_pewter_ledger_variant() -> PewterLedgerVariant:
    try:
        from hare.services.analytics.growthbook import get_feature_value_cached_may_be_stale

        raw = get_feature_value_cached_may_be_stale("tengu_pewter_ledger", None)
    except ImportError:
        raw = None
    if raw in ("trim", "cut", "cap"):
        return raw
    return None
