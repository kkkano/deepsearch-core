"""Firecrawl 全文抽取（高质量 markdown 输出）。"""

from __future__ import annotations

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.search.base import BaseReader

logger = structlog.get_logger(__name__)


class FirecrawlReader(BaseReader):
    name = "firecrawl"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    async def read(self, url: str) -> str:
        if not self.api_key:
            raise SearchError("FIRECRAWL_API_KEY not configured")

        try:
            resp = await self._client.post(
                "https://api.firecrawl.dev/v1/scrape",
                json={"url": url, "formats": ["markdown"]},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SearchError(f"Firecrawl error: {e}") from e

        data = resp.json()
        return data.get("data", {}).get("markdown", "")

    async def aclose(self) -> None:
        await self._client.aclose()
