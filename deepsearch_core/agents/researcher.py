"""ResearcherAgent: 执行单个 sub_query 的 ReAct 循环。"""

from __future__ import annotations

import asyncio

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.engine.state import Evidence, SubQuery
from deepsearch_core.retrieval.dedup import deduplicate_results
from deepsearch_core.retrieval.policy_filter import apply_policy_filter
from deepsearch_core.search.base import SearchResult

logger = structlog.get_logger(__name__)


class ResearcherAgent:
    """单个 researcher：HyDE → 多源检索 → reranker → 全文抽取 → 证据合成。"""

    def __init__(self, ctx: AgentContext, sub_query: SubQuery):
        self.ctx = ctx
        self.sub_query = sub_query

    async def run(self) -> list[Evidence]:
        # 1. HyDE：生成假设答案 (可选，加 latency 但提质量)
        queries: list[str] = [self.sub_query.text]
        if self.ctx.hyde:
            try:
                hyde_text = await self.ctx.hyde.generate(self.sub_query.text)
                queries.append(hyde_text[:300])  # 截断
            except Exception as e:
                logger.warning("hyde_failed", error=str(e))

        # 2. Query expansion
        if self.ctx.query_expander:
            try:
                expanded = await self.ctx.query_expander.expand(self.sub_query.text, n=2)
                queries.extend(expanded[1:])  # 跳过原 query
            except Exception as e:
                logger.warning("expansion_failed", error=str(e))

        # 3. 多引擎并行搜索
        all_results: list[SearchResult] = []
        async def _search_one(engine, q):
            try:
                return await engine.search(q, max_results=8)
            except Exception as e:
                logger.warning("search_failed", engine=engine.name, error=str(e))
                return []

        tasks = []
        for q in queries[:3]:  # 限制 query 数避免爆炸
            for engine in self.ctx.search_engines:
                tasks.append(_search_one(engine, q))
        results_lists = await asyncio.gather(*tasks)
        for rl in results_lists:
            all_results.extend(rl)

        # 4. 去重 + policy 过滤
        deduped = deduplicate_results(all_results)
        filtered = apply_policy_filter(deduped, self.ctx.policy)

        # 5. Reranker
        top_k = max(3, min(8, len(filtered)))
        if self.ctx.reranker and filtered:
            try:
                docs = [f"{r.title}\n{r.snippet}" for r in filtered]
                reranked = await self.ctx.reranker.rerank(self.sub_query.text, docs, top_k=top_k)
                filtered = [filtered[r.index] for r in reranked]
            except Exception as e:
                logger.warning("rerank_failed", error=str(e))
                filtered = filtered[:top_k]
        else:
            filtered = filtered[:top_k]

        # 6. 全文抽取（top-3 only，省 latency）
        if self.ctx.readers:
            reader = self.ctx.readers[0]

            async def _safe_read(r: SearchResult) -> None:
                try:
                    full = await asyncio.wait_for(reader.read(r.url), timeout=6.0)
                    if full:
                        r.full_text = full[:5000]
                except Exception as e:
                    logger.warning("reader_failed", url=r.url, error=str(e))

            await asyncio.gather(*[_safe_read(r) for r in filtered[:3]])

        # 7. 转 Evidence
        evidence = [
            Evidence(
                sub_query_id=self.sub_query.id,
                url=r.url,
                title=r.title,
                snippet=r.snippet,
                full_text=r.full_text,
                source=r.source,
                score=r.score,
                published_at=r.published_at,
                domain=r.domain,
            )
            for r in filtered
        ]
        return evidence
