"""Cron scheduler core (`cronScheduler.ts`). — simplified Python stub."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from hare.utils.cron import cron_to_human
from hare.utils.cron_tasks import CronTask


def is_recurring_task_aged(t: CronTask, now_ms: float, max_age_ms: float) -> bool:
    if max_age_ms == 0:
        return False
    return bool(t.recurring and not t.permanent and now_ms - t.created_at >= max_age_ms)


def build_missed_task_notification(missed: list[CronTask]) -> str:
    plural = len(missed) > 1
    header = (
        f"The following one-shot scheduled task{'s were' if plural else ' was'} missed while Claude was not running. "
        f"{'They have' if plural else 'It has'} already been removed from .claude/scheduled_tasks.json.\n\n"
        f"Do NOT execute {'these prompts' if plural else 'this prompt'} yet. "
        f"First use the AskUserQuestion tool to ask whether to run {'each one' if plural else 'it'} now. "
        f"Only execute if the user confirms."
    )
    blocks: list[str] = []
    for t in missed:
        meta = f"[{cron_to_human(t.cron)}, created {__import__('datetime').datetime.fromtimestamp(t.created_at/1000).isoformat()}]"
        runs = re.findall(r"`+", t.prompt)
        longest = max((len(x) for x in runs), default=0)
        fence = "`" * max(3, longest + 1)
        blocks.append(f"{meta}\n{fence}\n{t.prompt}\n{fence}")
    return f"{header}\n\n" + "\n\n".join(blocks)


@dataclass
class CronScheduler:
    start: Callable[[], None]
    stop: Callable[[], None]
    get_next_fire_time: Callable[[], float | None]


def create_cron_scheduler(options: dict[str, Any]) -> CronScheduler:
    """Stub scheduler: wire `on_fire` when full FS/watch integration exists."""

    def start() -> None:
        pass

    def stop() -> None:
        pass

    def get_next_fire_time() -> float | None:
        return None

    return CronScheduler(start=start, stop=stop, get_next_fire_time=get_next_fire_time)
