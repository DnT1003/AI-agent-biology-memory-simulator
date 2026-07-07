"""
Structured IO – NDJSON-safe message framing.

Port of: src/cli/structuredIO.ts + ndjsonSafeStringify.ts
"""
from __future__ import annotations
import json, sys
from typing import Any


def ndjson_safe_stringify(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class StructuredIO:
    def __init__(self, output: Any = None):
        self._output = output or sys.stdout

    def write_event(self, event_type: str, data: Any = None) -> None:
        msg = {"type": event_type}
        if data is not None:
            msg["data"] = data
        line = ndjson_safe_stringify(msg)
        self._output.write(line + "\n")
        self._output.flush()

    def write_text(self, text: str) -> None:
        self.write_event("text", {"content": text})

    def write_error(self, error: str) -> None:
        self.write_event("error", {"message": error})

    def write_result(self, data: Any) -> None:
        self.write_event("result", data)

    def write_tool_use(self, tool_name: str, tool_input: Any) -> None:
        self.write_event("tool_use", {"name": tool_name, "input": tool_input})

    def write_tool_result(self, tool_use_id: str, content: Any) -> None:
        self.write_event("tool_result", {"tool_use_id": tool_use_id, "content": content})
