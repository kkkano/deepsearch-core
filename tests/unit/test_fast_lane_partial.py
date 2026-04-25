"""测试 MEDIUM-1: fast_lane gather + wait_for 超时不丢已完成的搜索结果。

关键场景：3 个搜索引擎，2 个快（在 budget 内完成），1 个慢（超时）。
旧实现 wait_for(gather(...)) 整体取消会丢掉所有结果。
新实现 wait + cancel pending 必须保留快的那两个。
"""

from __future__ import annotations

import asyncio

import pytest

from deepsearch_core.search.base import BaseSearch, SearchResult


class _FakeSearch(BaseSearch):
    def __init__(self, name_: str, delay: float, results: list[SearchResult]):
        self.name = name_
        self.delay = delay
        self.results = results

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        await asyncio.sleep(self.delay)
        return self.results


@pytest.mark.asyncio
async def test_fast_lane_keeps_fast_results_even_if_one_engine_hangs():
    """模拟 fast_lane 关键代码段：超时只取消慢的，保留快的结果。"""
    fast1 = _FakeSearch("fast1", delay=0.05, results=[
        SearchResult(url="https://a.com/1", title="a", snippet="", score=0.9),
    ])
    fast2 = _FakeSearch("fast2", delay=0.05, results=[
        SearchResult(url="https://b.com/2", title="b", snippet="", score=0.8),
    ])
    slow = _FakeSearch("slow", delay=10.0, results=[])

    engines = [fast1, fast2, slow]
    budget = 0.5  # 远大于 fast 但远小于 slow

    # 复刻 fast_lane.py 修复后的核心逻辑
    async def _safe_search(engine, q):
        try:
            return await engine.search(q, max_results=10)
        except Exception:
            return []

    tasks = [asyncio.create_task(_safe_search(e, "q")) for e in engines]
    done, pending = await asyncio.wait(tasks, timeout=budget, return_when=asyncio.ALL_COMPLETED)
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    all_results = []
    for t in done:
        try:
            all_results.extend(t.result())
        except Exception:
            pass

    # 必须保留 fast1 和 fast2 的结果
    urls = {r.url for r in all_results}
    assert "https://a.com/1" in urls
    assert "https://b.com/2" in urls
    # slow 的没拿到（被 cancel）
    assert len(all_results) == 2
