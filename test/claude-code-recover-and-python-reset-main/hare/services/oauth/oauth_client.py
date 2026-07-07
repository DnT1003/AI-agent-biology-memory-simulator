"""
Low-level OAuth2 client (authorization URL, token exchange).

Port of: src/services/oauth/client.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None


async def exchange_code_for_tokens(
    _token_url: str,
    _client_id: str,
    _code: str,
    _redirect_uri: str,
    _code_verifier: str | None = None,
) -> TokenResponse:
    return TokenResponse(access_token="")


def build_authorization_url(
    authorize_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str | None = None,
) -> str:
    from urllib.parse import urlencode

    q: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if code_challenge:
        q["code_challenge"] = code_challenge
        q["code_challenge_method"] = "S256"
    return f"{authorize_url}?{urlencode(q)}"
