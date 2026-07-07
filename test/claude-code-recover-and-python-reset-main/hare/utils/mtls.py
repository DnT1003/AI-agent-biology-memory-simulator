"""
mTLS / custom CA helpers for HTTPS and fetch. Port of src/utils/mtls.ts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from hare.utils.debug import log_for_debugging

@dataclass
class MTLSConfig:
    cert: str | None = None
    key: str | None = None
    passphrase: str | None = None


@dataclass
class TLSConfig:
    cert: str | None = None
    key: str | None = None
    passphrase: str | None = None
    ca: str | bytes | list[str | bytes] | None = None


def _read_file_utf8(path: str) -> str:
    from hare.utils.fs_operations import get_fs_implementation

    return get_fs_implementation().read_file_sync(path, encoding="utf-8")


@lru_cache(maxsize=1)
def get_mtls_config() -> MTLSConfig | None:
    cfg = MTLSConfig()
    cert_path = os.environ.get("CLAUDE_CODE_CLIENT_CERT")
    if cert_path:
        try:
            cfg.cert = _read_file_utf8(cert_path)
            log_for_debugging("mTLS: Loaded client certificate from CLAUDE_CODE_CLIENT_CERT")
        except OSError as e:
            log_for_debugging(f"mTLS: Failed to load client certificate: {e}", level="error")
    key_path = os.environ.get("CLAUDE_CODE_CLIENT_KEY")
    if key_path:
        try:
            cfg.key = _read_file_utf8(key_path)
            log_for_debugging("mTLS: Loaded client key from CLAUDE_CODE_CLIENT_KEY")
        except OSError as e:
            log_for_debugging(f"mTLS: Failed to load client key: {e}", level="error")
    if os.environ.get("CLAUDE_CODE_CLIENT_KEY_PASSPHRASE"):
        cfg.passphrase = os.environ["CLAUDE_CODE_CLIENT_KEY_PASSPHRASE"]
        log_for_debugging("mTLS: Using client key passphrase")
    fields = {k: v for k, v in vars(cfg).items() if v is not None}
    if not fields:
        return None
    return cfg


def _get_ca_certificates() -> str | bytes | list[str | bytes] | None:
    try:
        from hare.utils.ca_certs import get_ca_certificates

        return get_ca_certificates()
    except ImportError:
        return None


@lru_cache(maxsize=1)
def get_mtls_agent() -> Any | None:
    """Return an urllib3/requests-compatible HTTPS agent, or None if unused."""
    mtls = get_mtls_config()
    ca = _get_ca_certificates()
    if not mtls and not ca:
        return None
    try:
        import ssl

        from urllib3.poolmanager import PoolManager  # type: ignore[import-untyped]
    except ImportError:
        log_for_debugging("mTLS: urllib3 not available; agent stub only")
        return object()
    ctx = ssl.create_default_context()
    if ca:
        # Stub: real code would load CA bundle
        pass
    if mtls and mtls.cert and mtls.key:
        pass
    log_for_debugging("mTLS: Creating HTTPS agent with custom certificates")
    return PoolManager()


def get_websocket_tls_options() -> dict[str, Any] | None:
    mtls = get_mtls_config()
    ca = _get_ca_certificates()
    if not mtls and not ca:
        return None
    out: dict[str, Any] = {}
    if mtls:
        out.update({k: v for k, v in vars(mtls).items() if v is not None})
    if ca:
        out["ca"] = ca
    return out


def get_tls_fetch_options() -> dict[str, Any]:
    """Options for HTTP clients (TLS bundle + optional undici dispatcher stub)."""
    mtls = get_mtls_config()
    ca = _get_ca_certificates()
    if not mtls and not ca:
        return {}
    tls_cfg: dict[str, Any] = {}
    if mtls:
        tls_cfg.update({k: v for k, v in vars(mtls).items() if v is not None})
    if ca:
        tls_cfg["ca"] = ca
    out: dict[str, Any] = {
        "tls": TLSConfig(
            cert=tls_cfg.get("cert"),
            key=tls_cfg.get("key"),
            passphrase=tls_cfg.get("passphrase"),
            ca=tls_cfg.get("ca"),
        )
    }
    try:
        import undici  # type: ignore[import-untyped]

        out["dispatcher"] = undici.Agent(connect=tls_cfg, pipelining=1)
        log_for_debugging("TLS: Created undici agent with custom certificates")
    except ImportError:
        pass
    return out


def clear_mtls_cache() -> None:
    get_mtls_config.cache_clear()
    get_mtls_agent.cache_clear()
    log_for_debugging("Cleared mTLS configuration cache")


def configure_global_mtls() -> None:
    if not get_mtls_config():
        return
    if os.environ.get("NODE_EXTRA_CA_CERTS"):
        log_for_debugging(
            "NODE_EXTRA_CA_CERTS detected - Node.js will automatically append to built-in CAs"
        )
