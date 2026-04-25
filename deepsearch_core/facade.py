"""DeepSearch 门面类：组装核心引擎所有依赖，提供高级 API。

用法：
    async with DeepSearch() as ds:
        result = await ds.quick_search("...")
        result = await ds.deep_search("...", depth=3, policy="finance")

        async for chunk in ds.stream("...", depth=3):
            ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.agents.critic import make_critic_node
from deepsearch_core.agents.fan_out import make_fan_out_research_node
from deepsearch_core.agents.planner import make_planner_node
from deepsearch_core.agents.reporter import make_reporter_node
from deepsearch_core.agents.supervisor import check_clarity_node, supervisor_node
from deepsearch_core.config import GlobalConfig, get_config
from deepsearch_core.engine.events import Event
from deepsearch_core.engine.fast_lane import run_quick_search
from deepsearch_core.engine.manager import RunManager
from deepsearch_core.engine.runner import GraphRunner
from deepsearch_core.engine.state import RunConfig, State
from deepsearch_core.engine.steer import SteerCommand, SteerScope
from deepsearch_core.llm.client import LLMClient
from deepsearch_core.policy.loader import PolicyConfig, load_policy
from deepsearch_core.reranker.cohere import CohereReranker
from deepsearch_core.retrieval.hyde import HyDEGenerator
from deepsearch_core.retrieval.query_expansion import QueryExpander
from deepsearch_core.search.crossref import CrossrefSearch
from deepsearch_core.search.duckduckgo import DuckDuckGoSearch
from deepsearch_core.search.firecrawl import FirecrawlReader
from deepsearch_core.search.jina_reader import JinaReader
from deepsearch_core.search.serper import SerperSearch
from deepsearch_core.search.tavily import TavilySearch
from deepsearch_core.store.store import EventStore

logger = structlog.get_logger(__name__)


class DeepSearch:
    """主入口：高级 API 封装。"""

    def __init__(self, config: GlobalConfig | None = None, store: EventStore | None = None):
        self.config = config or get_config()
        self.store = store or EventStore(self.config.store.dsn)
        self.llm = LLMClient(
            base_url=self.config.llm.base_url,
            api_key=self.config.llm.api_key,
        )
        # ---- 修复 #5：provider client 池（DeepSearch 实例级单例）----
        self._provider_pool: dict[str, Any] = self._init_provider_pool()
        self._runner_cache: dict[str, GraphRunner] = {}
        # ---- 修复 #1：跨适配统一 RunManager ----
        self.manager: RunManager = RunManager(self)

    def _init_provider_pool(self) -> dict[str, Any]:
        """一次性建好所有 search/reader/reranker client，全实例复用。"""
        pool: dict[str, Any] = {}
        if self.config.search.tavily_api_key:
            pool["tavily"] = TavilySearch(self.config.search.tavily_api_key)
        if self.config.search.serper_api_key:
            pool["serper"] = SerperSearch(self.config.search.serper_api_key)
        # 兜底 DDG（无 key 也能用）
        pool["duckduckgo"] = DuckDuckGoSearch()
        # 学术源（按需，但 client 提前建）
        pool["crossref"] = CrossrefSearch(
            base_url=self.config.search.crossref_base_url,
            mailto=self.config.search.crossref_mailto,
        )
        # Readers
        if self.config.search.firecrawl_api_key:
            pool["firecrawl"] = FirecrawlReader(self.config.search.firecrawl_api_key)
        pool["jina_reader"] = JinaReader(self.config.search.jina_reader_api_key)
        # Reranker
        if self.config.search.cohere_api_key:
            pool["cohere"] = CohereReranker(
                api_key=self.config.search.cohere_api_key,
                model=self.config.search.cohere_rerank_model,
            )
        return pool

    def _build_context(self, policy: str | dict | PolicyConfig) -> AgentContext:
        """从 provider pool 组装 ctx，client 全部复用，零新建开销。"""
        policy_cfg = load_policy(policy) if not isinstance(policy, PolicyConfig) else policy

        engines: list = []
        # 优先 Tavily / Serper / DDG（按 pool 是否有）
        for key in ("tavily", "serper"):
            if key in self._provider_pool:
                engines.append(self._provider_pool[key])
        if not engines:
            engines.append(self._provider_pool["duckduckgo"])
        if policy_cfg.academic_sources.get("crossref") and "crossref" in self._provider_pool:
            engines.append(self._provider_pool["crossref"])

        readers: list = []
        if "firecrawl" in self._provider_pool:
            readers.append(self._provider_pool["firecrawl"])
        readers.append(self._provider_pool["jina_reader"])

        reranker = self._provider_pool.get("cohere")
        hyde = HyDEGenerator(self.llm, self.config.llm.researcher_model)
        expander = QueryExpander(self.llm, self.config.llm.researcher_model)

        return AgentContext(
            llm=self.llm,
            policy=policy_cfg,
            search_engines=engines,
            readers=readers,
            reranker=reranker,
            hyde=hyde,
            query_expander=expander,
            _owns_clients=False,  # client 在 DeepSearch.aclose 集中关
            supervisor_model=self.config.llm.supervisor_model,
            planner_model=self.config.llm.planner_model,
            researcher_model=self.config.llm.researcher_model,
            critic_model=self.config.llm.critic_model,
            reporter_model=self.config.llm.reporter_model,
        )

    def _build_runner(self, ctx: AgentContext) -> GraphRunner:
        nodes = {
            "check_clarity": check_clarity_node,
            "supervisor": supervisor_node,
            "planner": make_planner_node(ctx),
            "fan_out_research": make_fan_out_research_node(ctx),
            "critic": make_critic_node(ctx),
            "reporter": make_reporter_node(ctx),
        }
        return GraphRunner(nodes=nodes, store=self.store)

    async def quick_search(self, query: str, policy: str = "general", max_results: int = 5, **kwargs) -> dict[str, Any]:
        """单轮快速搜索（Fast Lane，<8s 目标）。

        ---- 修复 #4 ----
        绕过 6 节点 graph，直接 search → policy_filter → reranker → fetch → reporter-lite。
        省掉 check_clarity / supervisor / planner / fan_out / critic。
        """
        timeout = int(kwargs.pop("timeout_seconds", 12))
        config = RunConfig(
            goal=query,
            depth=1,
            max_agents=1,
            max_steps_per_agent=1,
            policy=policy,
            timeout_seconds=timeout,
            enable_steer=False,
            **kwargs,
        )
        ctx = self._build_context(policy)
        final = await run_quick_search(
            ctx=ctx,
            query=query,
            config=config,
            store=self.store,
            max_results=max_results,
        )
        return _state_to_dict(final)

    async def deep_search(self, query: str, depth: int = 3, policy: str = "general", **kwargs) -> dict[str, Any]:
        """深度搜索（fan-out + critic + reporter）。"""
        config = RunConfig(
            goal=query,
            depth=depth,
            max_agents=self.config.engine.max_agents_fan_out,
            max_steps_per_agent=self.config.engine.max_steps_per_research,
            policy=policy,
            timeout_seconds=self.config.engine.task_timeout_seconds,
            enable_steer=True,
            **kwargs,
        )
        state = State(config=config)
        ctx = self._build_context(policy)
        runner = self._build_runner(ctx)
        final = await runner.run(state, start_node="check_clarity")
        return _state_to_dict(final)

    async def stream(
        self, query: str, depth: int = 3, policy: str = "general", **kwargs
    ) -> AsyncIterator[Event]:
        """流式：返回事件迭代器。"""
        config = RunConfig(
            goal=query,
            depth=depth,
            max_agents=self.config.engine.max_agents_fan_out,
            policy=policy,
            timeout_seconds=self.config.engine.task_timeout_seconds,
            **kwargs,
        )
        state = State(config=config)
        ctx = self._build_context(policy)
        runner = self._build_runner(ctx)

        # 启动 runner 异步任务，订阅 bus
        import asyncio

        run_task = asyncio.create_task(runner.run(state, start_node="check_clarity"))
        try:
            async for event in runner.stream_events(state.run_id):
                yield event
        finally:
            await run_task

    def steer(self, run_id: str, content: str, scope: str = "global") -> SteerCommand:
        """对 running task 注入 steer 命令。"""
        return self.store.add_steer(run_id, content, SteerScope(scope))

    def get_run(self, run_id: str) -> dict | None:
        return self.store.get_run(run_id)

    def list_events(self, run_id: str) -> list[Event]:
        return list(self.store.replay(run_id))

    async def aclose(self) -> None:
        # ---- 修复 #1：先取消所有 in-flight 任务 ----
        await self.manager.aclose()
        # ---- 修复 #5：关闭所有池化 client ----
        for name, client in list(self._provider_pool.items()):
            try:
                await client.aclose()
            except Exception:
                logger.exception("provider_aclose_failed", provider=name)
        self._provider_pool.clear()
        await self.llm.aclose()
        self.store.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()


def _state_to_dict(state: State) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "status": state.status.value,
        "elapsed_seconds": state.elapsed_seconds(),
        "report": state.report.model_dump() if state.report else None,
        "evidence_count": len(state.evidence),
        "citations": [c.model_dump() for c in (state.report.citations if state.report else [])],
        "token_usage": state.token_usage.model_dump(),
        "critic": state.critic_report.model_dump() if state.critic_report else None,
        "error": state.last_error,
    }
