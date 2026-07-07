"""
Session ID compatibility layer.

Port of: src/bridge/sessionIdCompat.ts
"""
from __future__ import annotations

_cse_shim_gate = False


def set_cse_shim_gate(enabled: bool) -> None:
    global _cse_shim_gate
    _cse_shim_gate = enabled


def to_compat_session_id(session_id: str) -> str:
    if _cse_shim_gate and session_id.startswith("session_"):
        return "cse_" + session_id[8:]
    return session_id


def to_infra_session_id(session_id: str) -> str:
    if session_id.startswith("cse_"):
        return "session_" + session_id[4:]
    return session_id
