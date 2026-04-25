"""Agent 基础设施：共享的 LLM client / search / reranker / policy 等。"""

from __future__ import annotations

from dataclasses import dataclass, field

from deepsearch_core.llm.client import LLMClient
from deepsearch_core.policy.loader import PolicyConfig
from deepsearch_core.reranker.base import BaseReranker
from deepsearch_core.retrieval.hyde import HyDEGenerator
from deepsearch_core.retrieval.query_expansion import QueryExpander
from deepsearch_core.search.base import BaseReader, BaseSearch


@dataclass
class AgentContext:
    """所有 agent 共享的依赖容器（DI 模式）。"""

    llm: LLMClient
    policy: PolicyConfig
    search_engines: list[BaseSearch] = field(default_factory=list)
    readers: list[BaseReader] = field(default_factory=list)
    reranker: BaseReranker | None = None
    hyde: HyDEGenerator | None = None
    query_expander: QueryExpander | None = None

    # 节点级模型配置
    supervisor_model: str = "claude-sonnet-4-6"
    planner_model: str = "claude-haiku-4-5"
    researcher_model: str = "claude-haiku-4-5"
    critic_model: str = "claude-sonnet-4-6"
    reporter_model: str = "claude-opus-4-7"


class BaseAgent:
    """Agent 基类（可选继承，本项目大量节点用纯函数）。"""

    name: str = "base"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
