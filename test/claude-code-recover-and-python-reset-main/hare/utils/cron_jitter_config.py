"""GrowthBook-backed cron jitter (`cronJitterConfig.ts`). — stub uses defaults."""

from __future__ import annotations

from typing import Any

from hare.utils.cron_tasks import DEFAULT_CRON_JITTER_CONFIG


def get_cron_jitter_config() -> dict[str, Any]:
    """Return validated jitter config; production wiring may use feature flags."""
    return dict(DEFAULT_CRON_JITTER_CONFIG)
