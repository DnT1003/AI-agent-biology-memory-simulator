"""
TLS / connection error classification for API clients.

Port of: src/services/api/errorUtils.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


_SSL_CODES = frozenset(
    {
        "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
        "UNABLE_TO_GET_ISSUER_CERT",
        "CERT_HAS_EXPIRED",
        "DEPTH_ZERO_SELF_SIGNED_CERT",
        "SELF_SIGNED_CERT_IN_CHAIN",
        "ERR_TLS_CERT_ALTNAME_INVALID",
        "HOSTNAME_MISMATCH",
    }
)


@dataclass
class ConnectionErrorDetails:
    code: str
    message: str
    is_ssl_error: bool


def extract_connection_error_details(error: BaseException | None) -> Optional[ConnectionErrorDetails]:
    if error is None:
        return None
    depth = 0
    current: BaseException | None = error
    while current is not None and depth < 5:
        code = getattr(current, "errno", None) or getattr(current, "code", None)
        if isinstance(code, str):
            return ConnectionErrorDetails(
                code=code,
                message=str(current),
                is_ssl_error=code in _SSL_CODES,
            )
        current = current.__cause__ if isinstance(current.__cause__, BaseException) else None
        depth += 1
    return None
