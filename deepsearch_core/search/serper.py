"""Serper.dev (Google Search API) 适配器。"""

from __future__ import annotations

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.search.base import BaseSearch, SearchResult

logger = structlog.get_logger(__name__)


class SerperSearch(BaseSearch):
    name = "serper"

    def __init__(self, api_key: str, timeout: float = 20.0):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not self.api_key:
            raise SearchError("SERPER_API_KEY not configured")

        try:
            resp = await self._client.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": max_results},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SearchError(f"Serper error: {e}") from e

        data = resp.json()
        organic = data.get("organic", [])
        return [
            SearchResult(
                url=r.get("link", ""),
                title=r.get("title", ""),
                snippet=r.get("snippet", ""),
                score=1.0 - i * 0.05,
                source="serper",
            )
            for i, r in enumerate(organic[:max_results])
            if r.get("link")
        ]

    async def aclose(self) -> None:
        await self._client.aclose()
