"""Datadog metrics sink (stub). Port of: src/services/analytics/datadog.ts"""

from __future__ import annotations

from typing import Any


async def send_datadog_metric(_name: str, _value: float, _tags: dict[str, str] | None = None) -> None:
    return


def datadog_sink_enabled() -> bool:
    return False
