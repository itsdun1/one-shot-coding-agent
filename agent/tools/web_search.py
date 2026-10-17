import asyncio
import logging
import os
from typing import Any

from exa_py import Exa

logger = logging.getLogger(__name__)


def web_search(
    query: str,
    num_results: int = 5,
    include_contents: bool = True,
) -> dict[str, Any]:
    """Search the web to find relevant information.

    Uses Exa by default, or Parallel when WEB_SEARCH_PROVIDER=parallel.

    Use this tool when you need to find documentation, code examples, GitHub repos,
    news, or research papers to help complete a task.

    Args:
        query: The search query
        num_results: Maximum number of results to return (default: 5)
        include_contents: Include page text (default: True). Exa returns full
            page contents; Parallel returns relevant excerpts instead.

    Returns:
        Dictionary containing:
        - success: Whether the search succeeded
        - results: Search results as a string
        - error: Error message if something failed
    """
    provider = os.environ.get("WEB_SEARCH_PROVIDER", "exa").strip().lower()
    if provider == "parallel":
        from .parallel_search import search_parallel

        try:
            return asyncio.run(search_parallel(query, num_results, include_contents))
        except Exception as e:
            logger.exception("parallel web_search failed")
            return {"success": False, "results": None, "error": f"{type(e).__name__}: {e}"}
    if provider != "exa":
        return {
            "success": False,
            "results": None,
            "error": f"Unknown WEB_SEARCH_PROVIDER: {provider!r}. Choose exa or parallel.",
        }

    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        logger.warning("exa_api_key_missing")
        return {
            "success": False,
            "error": "EXA_API_KEY is not configured. Please add it to your environment variables.",
        }

    async def _search() -> dict[str, Any]:
        client = Exa(api_key=api_key)
        if include_contents:
            result = await asyncio.to_thread(
                client.search_and_contents,
                query,
                text=True,
                num_results=num_results,
                type="auto",
            )
        else:
            result = await asyncio.to_thread(
                client.search,
                query,
                num_results=num_results,
                type="auto",
            )
        return {"success": True, "results": str(result), "error": None}

    try:
        return asyncio.run(_search())
    except Exception as e:
        logger.exception("web_search failed")
        return {"success": False, "results": None, "error": f"{type(e).__name__}: {e}"}
