"""Port of: src/utils/sessionStorage.ts"""
from __future__ import annotations
import json, os, time
from typing import Any, Optional

def get_transcript_path(session_id: str) -> str:
    base = os.path.join(os.path.expanduser("~"), ".claude", "transcripts")
    return os.path.join(base, f"{session_id}.jsonl")

def record_sidechain_transcript(session_id: str, data: dict[str, Any]) -> None:
    path = get_transcript_path(session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, default=str) + "\n")

def clear_session_messages_cache() -> None:
    pass

def set_agent_transcript_subdir(agent_id: str) -> None:
    pass

def clear_agent_transcript_subdir() -> None:
    pass

def write_agent_metadata(agent_id: str, metadata: dict[str, Any]) -> None:
    pass

def re_append_session_metadata() -> None:
    pass


def is_lite_log(data: dict[str, Any]) -> bool:
    """Check if a log entry is a lite log (reduced detail)."""
    return data.get("lite", False) or data.get("type") == "lite"


def load_full_log(session_id: str) -> list[dict[str, Any]]:
    """Load the full transcript log for a session."""
    path = get_transcript_path(session_id)
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries
