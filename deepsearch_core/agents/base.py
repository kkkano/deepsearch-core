"""Agent 基础设施：共享的 LLM client / search / reranker / policy 等。"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from deepsearch_core.llm.client import LLMClient
from deepsearch_core.policy.loader import PolicyConfig
from deepsearch_core.reranker.base import BaseReranker
from deepsearch_core.retrieval.hyde import HyDEGenerator
from deepsearch_core.retrieval.query_expansion import QueryExpander
from deepsearch_core.search.base import BaseReader, BaseSearch

_logger = structlog.get_logger(__name__)


@dataclass
class AgentContext:
    """所有 agent 共享的依赖容器（DI 模式）。

    生命周期：
    - 由 DeepSearch facade 通过 provider pool 共享，避免每次 _build_context 新建 client
    - 调 aclose() 关闭 search_engines / readers / reranker 内部 httpx client
    """

    llm: LLMClient
    policy: PolicyConfig
    search_engines: list[BaseSearch] = field(default_factory=list)
    readers: list[BaseReader] = field(default_factory=list)
    reranker: BaseReranker | None = None
    hyde: HyDEGenerator | None = None
    query_expander: QueryExpander | None = None
    _owns_clients: bool = False  # True = aclose 时关闭 search/reader/reranker

    # 节点级模型配置
    supervisor_model: str = "claude-sonnet-4-6"
    planner_model: str = "claude-haiku-4-5"
    researcher_model: str = "claude-haiku-4-5"
    critic_model: str = "claude-sonnet-4-6"
    reporter_model: str = "claude-opus-4-7"

    async def aclose(self) -> None:
        """释放本 ctx 持有的所有 provider client（仅当 _owns_clients=True）。"""
        if not self._owns_clients:
            return
        for e in self.search_engines:
            try:
                await e.aclose()
            except Exception:
                _logger.exception("search_engine_aclose_failed", engine=getattr(e, "name", "?"))
        for r in self.readers:
            try:
                await r.aclose()
            except Exception:
                _logger.exception("reader_aclose_failed", reader=getattr(r, "name", "?"))
        if self.reranker is not None:
            try:
                await self.reranker.aclose()
            except Exception:
                _logger.exception("reranker_aclose_failed")


class BaseAgent:
    """Agent 基类（可选继承，本项目大量节点用纯函数）。"""

    name: str = "base"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
