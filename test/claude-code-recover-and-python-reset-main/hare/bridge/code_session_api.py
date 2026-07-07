"""Port of: src/bridge/codeSessionApi.ts"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class RemoteCredentials:
    access_token: str = ""
    base_url: str = ""
    session_id: str = ""

async def create_code_session(access_token: str, base_url: str = "") -> dict[str, Any]:
    return {"session_id": "", "status": "created"}

async def fetch_remote_credentials(session_id: str, access_token: str, base_url: str = "") -> RemoteCredentials:
    return RemoteCredentials(access_token=access_token, base_url=base_url, session_id=session_id)
