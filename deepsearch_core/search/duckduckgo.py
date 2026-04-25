"""DuckDuckGo 搜索（兜底，无需 API key）。

注意：DDG 公开 API 限频严重，仅作 fallback。生产推荐 Tavily/Serper。
"""

from __future__ import annotations

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.search.base import BaseSearch, SearchResult

logger = structlog.get_logger(__name__)


class DuckDuckGoSearch(BaseSearch):
    name = "duckduckgo"

    def __init__(self, timeout: float = 20.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "deepsearch-core/0.1"},
        )

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        try:
            # 使用 DDG HTML endpoint
            resp = await self._client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SearchError(f"DuckDuckGo error: {e}") from e

        # 简化解析（生产建议用 ddgs / duckduckgo-search 库）
        text = resp.text
        results: list[SearchResult] = []
        # 这里用极简正则提取（v0.2 替换为 BeautifulSoup）
        import re

        pattern = re.compile(
            r'<a class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>.*?<a class="result__snippet"[^>]*>([^<]+)</a>',
            re.DOTALL,
        )
        for i, m in enumerate(pattern.finditer(text)):
            if i >= max_results:
                break
            url, title, snippet = m.groups()
            results.append(
                SearchResult(
                    url=url.strip(),
                    title=title.strip(),
                    snippet=snippet.strip(),
                    score=1.0 - i * 0.05,
                    source="duckduckgo",
                )
            )
        return results

    async def aclose(self) -> None:
        await self._client.aclose()
