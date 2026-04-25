"""Fan-Out 节点：N 个 ResearcherAgent 并行执行所有 sub_queries。"""

from __future__ import annotations

import asyncio

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.agents.researcher import ResearcherAgent
from deepsearch_core.engine.state import Evidence, State, SubQuery
from deepsearch_core.exceptions import DeepSearchError

logger = structlog.get_logger(__name__)


def make_fan_out_research_node(ctx: AgentContext):
    async def fan_out_research_node(state: State) -> tuple[State, str]:
        if not state.plan or not state.plan.sub_queries:
            raise DeepSearchError("fan_out called without a plan")

        max_concurrency = state.config.max_agents

        async def _run_one(sq: SubQuery) -> list[Evidence]:
            agent = ResearcherAgent(ctx, sq)
            return await agent.run()

        # 限制并发：用 semaphore
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(sq: SubQuery):
            async with sem:
                return await _run_one(sq)

        bundles = await asyncio.gather(*[_bounded(sq) for sq in state.plan.sub_queries])

        # 合并所有证据
        all_evidence: list[Evidence] = []
        for b in bundles:
            all_evidence.extend(b)

        new_state = state.with_update(evidence=all_evidence)
        return new_state, "critic"

    return fan_out_research_node


async def fan_out_research_node(state: State) -> tuple[State, str]:
    """占位 stub。"""
    return state, "critic"
