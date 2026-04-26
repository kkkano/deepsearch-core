"""Quick Search Fast Lane: 绕过 6 节点 graph，直达 <8s。

流程：
    search (multi-engine, racing) → policy_filter → reranker(top-K) →
    fetch top2 full text → reporter-lite (single LLM call)

省掉的环节：check_clarity / supervisor / planner / fan_out / critic
"""

from __future__ import annotations

import asyncio
import time

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.engine.state import (
    Citation,
    Evidence,
    Report,
    RunConfig,
    RunStatus,
    State,
    TokenUsage,
)
from deepsearch_core.exceptions import LLMError
from deepsearch_core.llm.client import Message
from deepsearch_core.retrieval.dedup import deduplicate_results
from deepsearch_core.retrieval.policy_filter import apply_policy_filter
from deepsearch_core.search.base import SearchResult

logger = structlog.get_logger(__name__)


QUICK_REPORTER_PROMPT = """You answer the user's question using ONLY the provided sources.

Rules:
- Cite sources inline as [^N] matching the order below
- If sources don't answer the question, say so honestly
- Be concise: 2-4 short paragraphs max
- Match the language of the question
- No preamble, no meta-commentary

Question: {question}

Sources:
{sources}

Answer:"""


async def run_quick_search(
    ctx: AgentContext,
    query: str,
    config: RunConfig,
    store=None,
    max_results: int = 5,
) -> State:
    """单轮快速搜索，无 graph 开销。"""
    state = State(config=config, current_node="quick_search")
    start = time.time()

    # ---- 持久化 + 起始事件 ----
    if store:
        store.create_run(state)
    state = state.with_update(status=RunStatus.RUNNING)

    try:
        # ---- 1. 多引擎并行搜索 (FIRST_COMPLETED race + merge top performer) ----
        async def _safe_search(engine, q: str) -> list[SearchResult]:
            try:
                return await engine.search(q, max_results=max_results * 2)
            except Exception as e:
                logger.warning("fast_lane_search_failed", engine=engine.name, error=str(e))
                return []

        budget = max(3.0, min(10.0, config.timeout_seconds * 0.35))
        engines = ctx.search_engines
        if not engines:
            raise LLMError("No search engines configured")

        # ---- 修复 MEDIUM-1：超时时保留已完成的结果，只取消 pending ----
        search_tasks = [asyncio.create_task(_safe_search(e, query)) for e in engines]
        done, pending = await asyncio.wait(
            search_tasks,
            timeout=budget,
            return_when=asyncio.ALL_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # 等被取消的 task 收尾，避免 warning
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        all_results: list[SearchResult] = []
        for t in done:
            try:
                all_results.extend(t.result())
            except Exception as e:
                logger.warning("fast_lane_search_task_failed", error=str(e))

        # ---- 2. 去重 + policy 过滤 ----
        deduped = deduplicate_results(all_results)
        filtered = apply_policy_filter(deduped, ctx.policy)

        # ---- 3. Reranker（如有，只对前 N 跑）----
        top_k = min(max_results, len(filtered))
        if ctx.reranker and filtered:
            try:
                docs = [f"{r.title}\n{r.snippet}" for r in filtered[:20]]
                rerank_budget = max(1.0, min(3.0, config.timeout_seconds * 0.15))
                reranked = await asyncio.wait_for(
                    ctx.reranker.rerank(query, docs, top_k=top_k),
                    timeout=rerank_budget,
                )
                filtered = [filtered[r.index] for r in reranked]
            except (TimeoutError, Exception) as e:
                logger.warning("fast_lane_rerank_failed", error=str(e))
                filtered = filtered[:top_k]
        else:
            filtered = filtered[:top_k]

        # ---- 4. 抓 top-2 全文（可选，节制延迟）----
        if ctx.readers and filtered:
            reader = ctx.readers[0]
            fetch_budget = max(1.0, min(3.0, config.timeout_seconds * 0.2))

            async def _safe_read(r: SearchResult):
                try:
                    full = await asyncio.wait_for(reader.read(r.url), timeout=fetch_budget)
                    if full:
                        r.full_text = full[:3000]
                except Exception:
                    pass

            await asyncio.gather(*[_safe_read(r) for r in filtered[:2]])

        # ---- 5. Reporter-lite: 单次 LLM 调用 ----
        sub_query_id = "quick"
        evidence = [
            Evidence(
                sub_query_id=sub_query_id,
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

        sources_block = "\n\n".join(
            f"[^{i + 1}] ({e.domain}) {e.title}\n  URL: {e.url}\n  {(e.full_text or e.snippet)[:600]}"
            for i, e in enumerate(evidence)
        )

        if not evidence:
            body_md = f"# {query}\n\n*No sources found within budget.*"
            tokens = TokenUsage()
        else:
            try:
                report_budget = max(2.0, config.timeout_seconds - (time.time() - start) - 0.5)
                resp = await asyncio.wait_for(
                    ctx.llm.chat(
                        model=ctx.reporter_model,
                        messages=[
                            Message(role="user", content=QUICK_REPORTER_PROMPT.format(question=query, sources=sources_block)),
                        ],
                        temperature=0.3,
                        max_tokens=1500,
                    ),
                    timeout=report_budget,
                )
                body_md = resp.content
                tokens = TokenUsage(
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    cached_tokens=resp.cached_tokens,
                    total_tokens=resp.prompt_tokens + resp.completion_tokens,
                )
            except (TimeoutError, Exception) as e:
                logger.warning("fast_lane_reporter_failed", error=str(e))
                body_md = f"# {query}\n\n*Report generation failed: {e}*\n\nSee citations below."
                tokens = TokenUsage()

        citations = [
            Citation(
                index=i + 1,
                url=e.url,
                title=e.title,
                snippet=e.snippet[:200],
                domain=e.domain,
            )
            for i, e in enumerate(evidence)
        ]
        report = Report(
            summary=body_md.split("\n", 1)[0][:300],
            body_markdown=body_md,
            citations=citations,
            confidence=0.7 if evidence else 0.0,
        )

        state = state.with_update(
            evidence=evidence,
            report=report,
            token_usage=tokens,
            status=RunStatus.COMPLETED,
            step_count=1,
        )

    except Exception as e:
        logger.exception("fast_lane_failed")
        state = state.with_update(status=RunStatus.FAILED, last_error=str(e))

    finally:
        from datetime import datetime
        state = state.with_update(finished_at=datetime.utcnow())
        if store:
            try:
                store.finish_run(state)
            except Exception:
                logger.exception("fast_lane_finish_failed", run_id=state.run_id)

    return state
