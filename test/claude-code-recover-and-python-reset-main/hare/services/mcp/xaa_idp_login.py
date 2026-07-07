"""
Enterprise IdP login for MCP (stub).

Port of: src/services/mcp/xaaIdpLogin.ts
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class XaaIdpSettings:
    issuer: str = ""
    client_id: str = ""


def is_xaa_enabled() -> bool:
    return False


def get_xaa_idp_settings() -> XaaIdpSettings | None:
    return None


async def acquire_idp_id_token() -> str | None:
    return None


def get_cached_idp_id_token() -> str | None:
    return None


def clear_idp_id_token() -> None:
    return


async def discover_oidc(_issuer: str) -> dict[str, str]:
    return {}


def get_idp_client_secret() -> str | None:
    return None
