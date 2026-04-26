"""Jina AI Reader（兜底 reader，免费 tier 可用）。"""

from __future__ import annotations

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.search.base import BaseReader

logger = structlog.get_logger(__name__)


class JinaReader(BaseReader):
    name = "jina_reader"

    def __init__(self, api_key: str = "", timeout: float = 8.0):
        headers: dict[str, str] = {"Accept": "text/markdown"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def read(self, url: str) -> str:
        try:
            # Jina Reader 用法：在 URL 前加 https://r.jina.ai/
            resp = await self._client.get(f"https://r.jina.ai/{url}")
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SearchError(f"Jina Reader error: {e}") from e

        return resp.text

    async def aclose(self) -> None:
        await self._client.aclose()
