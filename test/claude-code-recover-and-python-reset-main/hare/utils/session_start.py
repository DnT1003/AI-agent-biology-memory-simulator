"""Port of: src/utils/sessionStart.ts"""
from __future__ import annotations
from typing import Any

async def process_session_start_hooks() -> list[dict[str, Any]]:
    from hare.utils.hooks.hooks_config_manager import get_hooks_for_event
    hooks = get_hooks_for_event("session_start")
    results = []
    for hook in hooks:
        from hare.utils.hooks.exec_hook import exec_hook
        result = await exec_hook(hook.get("command", ""))
        results.append(result)
    return results
