"""Port of: src/bridge/debugUtils.ts"""
from __future__ import annotations
import re

def redact_secrets(text: str) -> str:
    return re.sub(r'(sk-ant-[a-zA-Z0-9]{6})[a-zA-Z0-9]+', r'\1***', text)

def debug_truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... ({len(text)} total)"

def debug_body(body: bytes | str, max_len: int = 500) -> str:
    s = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    return debug_truncate(redact_secrets(s), max_len)
