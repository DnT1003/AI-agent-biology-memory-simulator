"""
WebFetchTool – fetch URL content and process with AI.

Port of: src/tools/WebFetchTool/WebFetchTool.ts
"""
from __future__ import annotations
import urllib.request, urllib.error
from typing import Any
from hare.tools_impl.WebFetchTool.prompt import make_secondary_model_prompt

TOOL_NAME = "WebFetch"
WEB_FETCH_TOOL_NAME = TOOL_NAME

PREAPPROVED_DOMAINS = frozenset([
    "docs.python.org", "docs.anthropic.com", "developer.mozilla.org",
    "stackoverflow.com", "github.com", "pypi.org",
])

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "prompt": {"type": "string", "description": "What to extract"},
        },
        "required": ["url"],
    }

def _is_preapproved(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    return any(host.endswith(d) for d in PREAPPROVED_DOMAINS)

async def call(url: str, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
    if url.startswith("http://"):
        url = "https://" + url[7:]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ClaudeCode/2.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        if prompt:
            model_prompt = make_secondary_model_prompt(content[:50000], prompt, _is_preapproved(url))
            return {"data": model_prompt, "url": url, "contentLength": len(content)}
        return {"data": content[:50000], "url": url, "contentLength": len(content)}
    except Exception as e:
        return {"error": str(e), "url": url}
