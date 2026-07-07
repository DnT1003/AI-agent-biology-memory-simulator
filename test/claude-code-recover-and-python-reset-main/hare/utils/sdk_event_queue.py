"""
SDK event queue for headless / streaming consumers.

Port of: src/utils/sdkEventQueue.ts
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from uuid import UUID, uuid4

from hare.bootstrap.state import get_is_non_interactive_session, get_session_id

MAX_QUEUE_SIZE = 1000


class SdkWorkflowProgress(TypedDict, total=False):
    """Stub shape for workflow progress deltas (full schema in tools types)."""

    type: str
    index: int


class TaskStartedEvent(TypedDict, total=False):
    type: Literal["system"]
    subtype: Literal["task_started"]
    task_id: str
    tool_use_id: str
    description: str
    task_type: str
    workflow_name: str
    prompt: str


class TaskProgressUsage(TypedDict):
    total_tokens: int
    tool_uses: int
    duration_ms: int


class TaskProgressEvent(TypedDict, total=False):
    type: Literal["system"]
    subtype: Literal["task_progress"]
    task_id: str
    tool_use_id: str
    description: str
    usage: TaskProgressUsage
    last_tool_name: str
    summary: str
    workflow_progress: list[SdkWorkflowProgress]


class TaskNotificationSdkEvent(TypedDict, total=False):
    type: Literal["system"]
    subtype: Literal["task_notification"]
    task_id: str
    tool_use_id: str
    status: Literal["completed", "failed", "stopped"]
    output_file: str
    summary: str
    usage: TaskProgressUsage


class SessionStateChangedEvent(TypedDict):
    type: Literal["system"]
    subtype: Literal["session_state_changed"]
    state: Literal["idle", "running", "requires_action"]


SdkEvent = (
    TaskStartedEvent
    | TaskProgressEvent
    | TaskNotificationSdkEvent
    | SessionStateChangedEvent
)

_queue: list[SdkEvent] = []


def enqueue_sdk_event(event: SdkEvent) -> None:
    """Queue an SDK event (non-interactive sessions only)."""
    if not get_is_non_interactive_session():
        return
    if len(_queue) >= MAX_QUEUE_SIZE:
        _queue.pop(0)
    _queue.append(event)


@dataclass
class DrainedSdkEvent:
    """Event with session metadata after drain."""

    event: dict[str, Any]
    uuid: UUID
    session_id: str


def drain_sdk_events() -> list[dict[str, Any]]:
    """Drain all queued events, annotating with uuid and session_id."""
    if not _queue:
        return []
    events = _queue[:]
    _queue.clear()
    sid = get_session_id()
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(copy.deepcopy(e))
        row["uuid"] = str(uuid4())
        row["session_id"] = sid
        out.append(row)
    return out


def emit_task_terminated_sdk(
    task_id: str,
    status: Literal["completed", "failed", "stopped"],
    *,
    tool_use_id: str | None = None,
    summary: str | None = None,
    output_file: str | None = None,
    usage: TaskProgressUsage | None = None,
) -> None:
    """Emit task_notification when a task reaches a terminal state."""
    enqueue_sdk_event(
        TaskNotificationSdkEvent(
            type="system",
            subtype="task_notification",
            task_id=task_id,
            tool_use_id=tool_use_id,
            status=status,
            output_file=output_file or "",
            summary=summary or "",
            usage=usage,
        )
    )
