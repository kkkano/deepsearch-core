"""Multi-Engine Racing：并行多引擎，谁先返回用谁 + 合并。"""

from __future__ import annotations

import asyncio

import structlog

from deepsearch_core.search.base import BaseSearch, SearchResult

logger = structlog.get_logger(__name__)


class MultiEngineSearch:
    """并行多个搜索引擎，合并结果。"""

    def __init__(self, engines: list[BaseSearch]):
        self.engines = [e for e in engines if e is not None]

    async def search_first(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """返回最先成功的引擎的结果（速度优先）。"""
        if not self.engines:
            return []

        tasks = [asyncio.create_task(e.search(query, max_results)) for e in self.engines]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                if not t.exception():
                    return t.result()
        finally:
            await asyncio.gather(*[t for t in tasks if not t.done()], return_exceptions=True)
        return []

    async def search_merge(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """并行所有引擎，合并去重（质量优先）。"""
        if not self.engines:
            return []

        async def safe_call(e: BaseSearch) -> list[SearchResult]:
            try:
                return await e.search(query, max_results)
            except Exception as exc:
                logger.warning("engine_error", engine=e.name, error=str(exc))
                return []

        all_results = await asyncio.gather(*[safe_call(e) for e in self.engines])
        merged: dict[str, SearchResult] = {}
        for results in all_results:
            for r in results:
                key = r.url.rstrip("/").lower()
                if key not in merged or merged[key].score < r.score:
                    merged[key] = r
        return sorted(merged.values(), key=lambda x: -x.score)[:max_results]

    async def aclose(self) -> None:
        for e in self.engines:
            await e.aclose()
