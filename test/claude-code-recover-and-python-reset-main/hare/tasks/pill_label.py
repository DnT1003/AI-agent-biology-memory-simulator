"""Footer pill labels for background tasks (port of src/tasks/pillLabel.ts)."""

from __future__ import annotations

from typing import Any, Literal

DIAMOND_FILLED = "◆"
DIAMOND_OPEN = "◇"


def _count(items: list[Any], pred) -> int:
    return sum(1 for x in items if pred(x))


def get_pill_label(tasks: list[dict[str, Any]]) -> str:
    n = len(tasks)
    if n == 0:
        return "0 background tasks"
    t0 = tasks[0].get("type")
    if all(t.get("type") == t0 for t in tasks):
        match t0:
            case "local_bash":
                monitors = _count(tasks, lambda t: t.get("kind") == "monitor")
                shells = n - monitors
                parts: list[str] = []
                if shells:
                    parts.append("1 shell" if shells == 1 else f"{shells} shells")
                if monitors:
                    parts.append("1 monitor" if monitors == 1 else f"{monitors} monitors")
                return ", ".join(parts)
            case "in_process_teammate":
                teams = len({t.get("identity", {}).get("teamName", "") for t in tasks})
                return "1 team" if teams == 1 else f"{teams} teams"
            case "local_agent":
                return "1 local agent" if n == 1 else f"{n} local agents"
            case "remote_agent":
                first = tasks[0]
                if n == 1 and first.get("isUltraplan"):
                    phase = first.get("ultraplanPhase")
                    if phase == "plan_ready":
                        return f"{DIAMOND_FILLED} ultraplan ready"
                    if phase == "needs_input":
                        return f"{DIAMOND_OPEN} ultraplan needs your input"
                    return f"{DIAMOND_OPEN} ultraplan"
                return (
                    f"{DIAMOND_OPEN} 1 cloud session"
                    if n == 1
                    else f"{DIAMOND_OPEN} {n} cloud sessions"
                )
            case "local_workflow":
                return "1 background workflow" if n == 1 else f"{n} background workflows"
            case "monitor_mcp":
                return "1 monitor" if n == 1 else f"{n} monitors"
            case "dream":
                return "dreaming"
    return f"{n} background {'task' if n == 1 else 'tasks'}"


def pill_needs_cta(tasks: list[dict[str, Any]]) -> bool:
    if len(tasks) != 1:
        return False
    t = tasks[0]
    return bool(
        t.get("type") == "remote_agent"
        and t.get("isUltraplan")
        and t.get("ultraplanPhase") is not None
    )
