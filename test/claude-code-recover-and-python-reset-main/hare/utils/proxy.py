"""
HTTP(S) proxy resolution, NO_PROXY, and fetch client options. Port of src/utils/proxy.ts.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from hare.utils.debug import log_for_debugging
from hare.utils.env_utils import is_env_truthy
from hare.utils.mtls import get_mtls_config, get_tls_fetch_options

_keep_alive_disabled = False


def disable_keep_alive() -> None:
    global _keep_alive_disabled
    _keep_alive_disabled = True


def _reset_keep_alive_for_testing() -> None:
    global _keep_alive_disabled
    _keep_alive_disabled = False


def get_address_family(options: dict[str, Any]) -> int:
    fam = options.get("family")
    if fam in (0, 4, 6):
        return fam
    if fam == "IPv6":
        return 6
    if fam in ("IPv4", None):
        return 4
    raise ValueError(f"Unsupported address family: {fam}")


EnvLike = dict[str, str | None]


def get_proxy_url(env: EnvLike | None = None) -> str | None:
    e = env if env is not None else os.environ
    return e.get("https_proxy") or e.get("HTTPS_PROXY") or e.get("http_proxy") or e.get("HTTP_PROXY")


def get_no_proxy(env: EnvLike | None = None) -> str | None:
    e = env if env is not None else os.environ
    return e.get("no_proxy") or e.get("NO_PROXY")


def should_bypass_proxy(url_string: str, no_proxy: str | None = None) -> bool:
    np = no_proxy if no_proxy is not None else get_no_proxy()
    if not np:
        return False
    if np == "*":
        return True
    try:
        u = urlparse(url_string)
        hostname = (u.hostname or "").lower()
        port = u.port or (443 if u.scheme == "https" else 80)
        host_with_port = f"{hostname}:{port}"
        for raw in re.split(r"[\s,]+", np):
            pattern = raw.strip().lower()
            if not pattern:
                continue
            if ":" in pattern:
                if host_with_port == pattern:
                    return True
            elif pattern.startswith("."):
                suf = pattern
                if hostname == pattern[1:] or hostname.endswith(suf):
                    return True
            elif hostname == pattern:
                return True
    except Exception:
        return False
    return False


@lru_cache(maxsize=16)
def get_proxy_agent(uri: str) -> Any:
    """Return an httpx/urllib3 dispatcher stub for `uri` (undici EnvHttpProxyAgent analogue)."""
    try:
        import httpx

        mtls = get_mtls_config()
        ca = getattr(mtls, "ca", None) if mtls else None
        return httpx.Client(proxy=uri, verify=ca if ca else True)
    except ImportError:
        return {"proxy": uri, "no_proxy": get_no_proxy()}


def get_websocket_proxy_agent(url: str) -> Any | None:
    p = get_proxy_url()
    if not p or should_bypass_proxy(url):
        return None
    return get_proxy_agent(p)


def get_websocket_proxy_url(url: str) -> str | None:
    p = get_proxy_url()
    if not p or should_bypass_proxy(url):
        return None
    return p


def get_proxy_fetch_options(*, for_anthropic_api: bool = False) -> dict[str, Any]:
    base: dict[str, Any] = {}
    if _keep_alive_disabled:
        base["keepalive"] = False
    if for_anthropic_api and os.environ.get("ANTHROPIC_UNIX_SOCKET"):
        return {**base, "unix": os.environ["ANTHROPIC_UNIX_SOCKET"]}
    p = get_proxy_url()
    if p:
        return {**base, "dispatcher": get_proxy_agent(p)}
    return {**base, **get_tls_fetch_options()}


def configure_global_agents() -> None:
    """Stub: configure process-wide HTTP clients when httpx/requests wrappers exist."""
    log_for_debugging(f"configure_global_agents (proxy={get_proxy_url()!r})")


async def get_aws_client_proxy_config() -> dict[str, Any]:
    if not get_proxy_url():
        return {}
    return {"requestHandler": "stub", "credentials": "default-provider"}


def clear_proxy_cache() -> None:
    get_proxy_agent.cache_clear()
    log_for_debugging("Cleared proxy agent cache")
