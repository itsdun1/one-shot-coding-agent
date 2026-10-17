"""Anonymous Parallel Search MCP backend for the existing web_search tool."""

import asyncio
import json
from typing import Any

import httpx

PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
PARALLEL_USER_AGENT = "one-shot-coding-agent/0.1.0"
PARALLEL_SEARCH_TIMEOUT = 60


async def search_parallel(query: str, num_results: int, include_contents: bool) -> dict[str, Any]:
    """Return search excerpts using the optional MCP SDK, without credentials."""
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise RuntimeError(
            "Parallel search requires the parallel extra. Run uv sync --extra parallel."
        ) from exc

    if num_results < 1:
        raise ValueError("num_results must be at least 1")

    async with asyncio.timeout(PARALLEL_SEARCH_TIMEOUT):
        async with httpx.AsyncClient(
            headers={"User-Agent": PARALLEL_USER_AGENT}, timeout=30
        ) as client:
            async with streamable_http_client(PARALLEL_MCP_URL, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "web_search", {"objective": query, "search_queries": [query]}
                    )

    text = "\n".join(block.text for block in result.content if block.type == "text")
    if result.isError:
        raise RuntimeError(f"Parallel search failed: {text}")
    data = result.structuredContent
    if data is None:
        data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Parallel search returned an invalid results payload")

    # Anonymous MCP settings are server-managed. Apply the caller's output
    # preferences locally rather than sending unsupported search overrides.
    results = []
    for item in data["results"][:num_results]:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            raise ValueError("Parallel search returned an invalid result")
        entry = dict(item)
        if not include_contents:
            entry.pop("excerpts", None)
        results.append(entry)
    return {"success": True, "results": json.dumps(results), "error": None}
