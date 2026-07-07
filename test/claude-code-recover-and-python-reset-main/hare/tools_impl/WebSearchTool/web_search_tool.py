"""
WebSearchTool – web search via Anthropic beta API.

Port of: src/tools/WebSearchTool/WebSearchTool.ts
"""
from __future__ import annotations
import time
from typing import Any

TOOL_NAME = "WebSearch"
WEB_SEARCH_TOOL_NAME = TOOL_NAME

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "allowed_domains": {"type": "array", "items": {"type": "string"}},
            "blocked_domains": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
    }

async def call(
    query: str,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    start = time.time()
    from hare.services.api import create_api_client
    client = create_api_client()
    try:
        result = await client.web_search(
            query=query,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )
        return {
            "query": query,
            "results": result.get("results", []),
            "durationSeconds": time.time() - start,
        }
    except Exception as e:
        return {"query": query, "results": [], "error": str(e)}
