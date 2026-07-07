"""Load and deserialize transcripts for resume (`conversationRecovery.ts`)."""

from __future__ import annotations

from typing import Any, Literal

TurnInterruptionKind = Literal["none", "interrupted_prompt", "interrupted_turn"]


def deserialize_messages(serialized_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    r = deserialize_messages_with_interrupt_detection(serialized_messages)
    return r["messages"]


def deserialize_messages_with_interrupt_detection(
    serialized_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Stub: full migration/filter pipeline lives in `messages` + `session_storage`."""
    return {
        "messages": list(serialized_messages),
        "turnInterruptionState": {"kind": "none"},
    }


async def load_conversation_for_resume(
    source: str | dict[str, Any] | None,
    source_jsonl_file: str | None = None,
) -> dict[str, Any] | None:
    """Central resume loader — integrate with `session_storage` when available."""
    return None


def restore_skill_state_from_messages(messages: list[dict[str, Any]]) -> None:
    for msg in messages:
        if msg.get("type") != "attachment":
            continue
        att = msg.get("attachment") or {}
        if att.get("type") == "invoked_skills":
            try:
                from hare.bootstrap.state import add_invoked_skill  # type: ignore[import-not-found]

                for sk in att.get("skills") or []:
                    name, path, content = sk.get("name"), sk.get("path"), sk.get("content")
                    if name and path and content:
                        add_invoked_skill(name, path, content, None)
            except ImportError:
                pass
