"""Tavily Search API 适配器。"""

from __future__ import annotations

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.search.base import BaseSearch, SearchResult

logger = structlog.get_logger(__name__)


class TavilySearch(BaseSearch):
    name = "tavily"

    def __init__(self, api_key: str, timeout: float = 20.0):
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not self.api_key:
            raise SearchError("TAVILY_API_KEY not configured")

        try:
            resp = await self._client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SearchError(f"Tavily error: {e}") from e

        data = resp.json()
        return [
            SearchResult(
                url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=r.get("content", ""),
                score=float(r.get("score", 0.5)),
                source="tavily",
            )
            for r in data.get("results", [])
            if r.get("url")
        ]

    async def aclose(self) -> None:
        await self._client.aclose()
