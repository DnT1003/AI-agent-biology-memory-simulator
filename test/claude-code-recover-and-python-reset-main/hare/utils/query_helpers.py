"""
Query / SDK message normalization helpers. Port of src/utils/queryHelpers.ts (subset).
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from hare.bootstrap.state import is_session_persistence_disabled
from hare.tools_impl.BashTool.prompt import BASH_TOOL_NAME
from hare.tools_impl.FileEditTool.prompt import FILE_EDIT_TOOL_NAME
from hare.tools_impl.FileReadTool.prompt import FILE_READ_TOOL_NAME, FILE_UNCHANGED_STUB
from hare.tools_impl.FileWriteTool.prompt import FILE_WRITE_TOOL_NAME
from hare.utils.env_utils import is_env_truthy
from hare.utils.file import get_file_modification_time, read_file_sync_with_metadata
from hare.utils.file_state_cache import (
    FileState,
    FileStateCache,
    create_file_state_cache_with_size_limit,
)
from hare.utils.path_utils import expand_path

ASK_READ_FILE_STATE_CACHE_SIZE = 10

_SYSTEM_REMINDER = re.compile(r"<system-reminder>[\s\S]*?</system-reminder>")


def _is_fs_inaccessible(exc: BaseException) -> bool:
    return isinstance(exc, (FileNotFoundError, PermissionError, OSError))


def strip_line_number_prefix(line: str) -> str:
    m = re.match(r"^\s*\d+[\u2192\t](.*)$", line)
    return m.group(1) if m else line


def is_result_successful(message: Any | None, stop_reason: str | None = None) -> bool:
    if message is None:
        return False
    t = getattr(message, "type", None)
    if t == "assistant":
        content = getattr(getattr(message, "message", None), "content", None)
        if isinstance(content, list) and content:
            last = content[-1]
            if isinstance(last, dict):
                return last.get("type") in ("text", "thinking", "redacted_thinking")
        return False
    if t == "user":
        content = getattr(getattr(message, "message", None), "content", None)
        if isinstance(content, list) and content:
            return all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return stop_reason == "end_turn"


async def normalize_message(message: Any) -> AsyncGenerator[dict[str, Any], None]:
    """Map internal Message → SDK message shapes (simplified)."""
    _ = message
    yield {"type": "stub", "note": "normalize_message full port pending"}


async def handle_orphaned_permission(
    orphaned_permission: Any,
    tools: Any,
    mutable_messages: list[Any],
    process_user_input_context: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    """Resume tool execution after permission prompt (requires tool orchestration)."""
    try:
        from hare.services.tools.tool_orchestration import run_tools
    except ImportError:
        return
    _ = (orphaned_permission, tools, mutable_messages, process_user_input_context, run_tools)
    yield {"type": "stub"}


def extract_read_files_from_messages(
    messages: list[Any],
    cwd: str,
    max_size: int = ASK_READ_FILE_STATE_CACHE_SIZE,
) -> FileStateCache:
    cache = create_file_state_cache_with_size_limit(max_size)
    file_read_ids: dict[str, str] = {}
    file_write_ids: dict[str, dict[str, str]] = {}
    file_edit_ids: dict[str, str] = {}
    for message in messages:
        if getattr(message, "type", None) != "assistant":
            continue
        content = getattr(getattr(message, "message", None), "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tid = block.get("id")
            inp = block.get("input") or {}
            if name == FILE_READ_TOOL_NAME and tid:
                if inp.get("file_path") and inp.get("offset") is None and inp.get("limit") is None:
                    file_read_ids[tid] = expand_path(inp["file_path"], cwd)
            elif name == FILE_WRITE_TOOL_NAME and tid:
                if inp.get("file_path") and inp.get("content") is not None:
                    file_write_ids[tid] = {
                        "filePath": expand_path(inp["file_path"], cwd),
                        "content": str(inp.get("content", "")),
                    }
            elif name == FILE_EDIT_TOOL_NAME and tid:
                fp = inp.get("file_path")
                if fp:
                    file_edit_ids[tid] = expand_path(fp, cwd)
    _ = is_session_persistence_disabled

    def _ts_ms(ts: Any) -> float:
        if isinstance(ts, (int, float)):
            return float(ts)
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000
        except Exception:
            return 0.0

    for message in messages:
        if getattr(message, "type", None) != "user":
            continue
        content = getattr(getattr(message, "message", None), "content", None)
        if not isinstance(content, list):
            continue
        ts = _ts_ms(getattr(message, "timestamp", None))
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tuid = block.get("tool_use_id")
            if not tuid:
                continue
            body = block.get("content")
            if isinstance(body, str) and tuid in file_read_ids:
                fp = file_read_ids[tuid]
                if body.startswith(FILE_UNCHANGED_STUB):
                    continue
                cleaned = _SYSTEM_REMINDER.sub("", body)
                file_content = "\n".join(
                    strip_line_number_prefix(ln) for ln in cleaned.split("\n")
                ).strip()
                cache.set(fp, FileState(content=file_content, timestamp=ts, offset=None, limit=None))
            wt = file_write_ids.get(tuid)
            if wt:
                cache.set(
                    wt["filePath"],
                    FileState(content=wt["content"], timestamp=ts, offset=None, limit=None),
                )
            ed = file_edit_ids.get(tuid)
            if ed and block.get("is_error") is not True:
                try:
                    disk = read_file_sync_with_metadata(ed)
                    cache.set(
                        ed,
                        FileState(
                            content=disk["content"],
                            timestamp=float(get_file_modification_time(ed)),
                            offset=None,
                            limit=None,
                        ),
                    )
                except OSError as e:
                    if not _is_fs_inaccessible(e):
                        raise
    return cache


def extract_bash_tools_from_messages(messages: list[Any]) -> set[str]:
    tools: set[str] = set()
    for message in messages:
        if getattr(message, "type", None) != "assistant":
            continue
        content = getattr(getattr(message, "message", None), "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == BASH_TOOL_NAME:
                inp = block.get("input") or {}
                cmd = inp.get("command") if isinstance(inp, dict) else None
                name = _extract_cli_name(cmd if isinstance(cmd, str) else None)
                if name:
                    tools.add(name)
    return tools


_STRIPPED = frozenset({"sudo"})


def _extract_cli_name(command: str | None) -> str | None:
    if not command:
        return None
    for tok in command.strip().split():
        if re.match(r"^[A-Za-z_]\w*=", tok):
            continue
        if tok in _STRIPPED:
            continue
        return tok
    return None
