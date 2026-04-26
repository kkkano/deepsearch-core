"""Crossref 学术元数据 API。"""

from __future__ import annotations

from datetime import datetime

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.search.base import BaseSearch, SearchResult

logger = structlog.get_logger(__name__)


class CrossrefSearch(BaseSearch):
    """Crossref 学术论文搜索：按 query 返回 DOI + 元数据。"""

    name = "crossref"

    def __init__(
        self,
        base_url: str = "https://api.crossref.org",
        mailto: str = "",
        timeout: float = 20.0,
    ):
        headers = {"User-Agent": "deepsearch-core/0.1"}
        if mailto:
            headers["User-Agent"] += f" (mailto:{mailto})"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "query": query,
            "rows": max_results,
            "sort": "relevance",
        }
        if self.mailto:
            params["mailto"] = self.mailto

        try:
            resp = await self._client.get(f"{self.base_url}/works", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SearchError(f"Crossref error: {e}") from e

        data = resp.json()
        items = data.get("message", {}).get("items", [])
        results: list[SearchResult] = []

        for i, item in enumerate(items):
            title = item.get("title", [""])[0] if item.get("title") else ""
            url = item.get("URL") or (f"https://doi.org/{item.get('DOI')}" if item.get("DOI") else "")
            if not url:
                continue

            authors = ", ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in item.get("author", [])[:3]
            )
            container = item.get("container-title", [""])[0] if item.get("container-title") else ""
            abstract = item.get("abstract", "").replace("<jats:p>", "").replace("</jats:p>", "")[:500]
            snippet = f"{authors} | {container}\n{abstract}" if authors else abstract

            published = None
            date_parts = item.get("issued", {}).get("date-parts", [[]])[0]
            if date_parts and len(date_parts) >= 1:
                try:
                    published = datetime(
                        date_parts[0],
                        date_parts[1] if len(date_parts) > 1 else 1,
                        date_parts[2] if len(date_parts) > 2 else 1,
                    )
                except (TypeError, ValueError):
                    pass

            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    score=1.0 - i * 0.05,
                    source="crossref",
                    published_at=published,
                )
            )

        return results

    async def aclose(self) -> None:
        await self._client.aclose()
