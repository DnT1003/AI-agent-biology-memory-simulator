"""
Text input types for prompt/command queue.

Port of: src/types/textInputTypes.ts
"""

from __future__ import annotations

from typing import Any, Literal

PromptInputMode = Literal["bash", "prompt", "orphaned-permission", "task-notification"]
EditablePromptInputMode = Literal["bash", "prompt"]

QueuePriority = Literal["now", "next", "later"]

VimMode = Literal["INSERT", "NORMAL"]


class QueuedCommand:
    """A queued command waiting to be processed."""

    def __init__(
        self,
        value: str | list[dict[str, Any]] = "",
        mode: PromptInputMode = "prompt",
        priority: QueuePriority | None = None,
        uuid: str | None = None,
        skip_slash_commands: bool = False,
        bridge_origin: bool = False,
        is_meta: bool = False,
        origin: str | None = None,
        workload: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.value = value
        self.mode = mode
        self.priority = priority
        self.uuid = uuid
        self.skip_slash_commands = skip_slash_commands
        self.bridge_origin = bridge_origin
        self.is_meta = is_meta
        self.origin = origin
        self.workload = workload
        self.agent_id = agent_id


class OrphanedPermission:
    """Permission result for an orphaned tool use."""

    def __init__(
        self,
        permission_result: dict[str, Any] | None = None,
        assistant_message: dict[str, Any] | None = None,
    ) -> None:
        self.permission_result = permission_result
        self.assistant_message = assistant_message


def is_valid_image_paste(content: dict[str, Any]) -> bool:
    return content.get("type") == "image" and len(content.get("content", "")) > 0


def get_image_paste_ids(
    pasted_contents: dict[int, dict[str, Any]] | None,
) -> list[int] | None:
    if not pasted_contents:
        return None
    ids = [c["id"] for c in pasted_contents.values() if is_valid_image_paste(c)]
    return ids if ids else None
