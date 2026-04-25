"""核心状态对象 + 数据模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class TokenUsage(BaseModel):
    """LLM token 计数。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, prompt: int, completion: int, cached: int = 0) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.cached_tokens += cached
        self.total_tokens = self.prompt_tokens + self.completion_tokens


class SubQuery(BaseModel):
    """planner 拆出来的子查询。"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str
    angle: str = "general"  # general / official / news / community / academic
    priority: int = 5
    status: Literal["pending", "running", "completed", "failed"] = "pending"


class Plan(BaseModel):
    """planner 节点输出。"""

    rationale: str = ""
    sub_queries: list[SubQuery] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    revision: int = 1


class Evidence(BaseModel):
    """单条证据。"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    sub_query_id: str
    url: str
    title: str
    snippet: str
    full_text: str | None = None
    source: str = "unknown"
    score: float = 0.0
    published_at: datetime | None = None
    domain: str = ""


class Citation(BaseModel):
    """报告中的引用。"""

    index: int
    url: str
    title: str
    snippet: str
    domain: str = ""
    char_range: tuple[int, int] | None = None  # 报告中引用的字符范围


class CriticReport(BaseModel):
    """critic 节点产物。"""

    confidence: float
    conflicts: list[str] = Field(default_factory=list)
    counter_arguments: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


class Report(BaseModel):
    """reporter 节点产物。"""

    summary: str
    body_markdown: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0


class RunConfig(BaseModel):
    """单次运行配置。"""

    goal: str
    depth: int = 3  # 1=quick, 2=standard, 3=deep, 4-5=extra-deep
    max_agents: int = 4
    max_steps_per_agent: int = 8
    policy: str | dict = "general"  # 名字或 inline dict
    timeout_seconds: int = 300
    enable_steer: bool = True
    enable_event_sourcing: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class State(BaseModel):
    """整个 graph 流转的 state。"""

    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    config: RunConfig
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING

    # 节点产物
    clarification: str | None = None
    plan: Plan | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    critic_report: CriticReport | None = None
    report: Report | None = None

    # 控制
    current_node: str = "check_clarity"
    interrupt_requested: bool = False
    steer_payload: dict[str, Any] | None = None

    # Bookkeeping
    step_count: int = 0
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    last_error: str | None = None

    def elapsed_seconds(self) -> float:
        return (datetime.utcnow() - self.started_at).total_seconds()

    def with_update(self, **kwargs) -> State:
        """immutable 更新（避免到处 mutation）。"""
        return self.model_copy(update=kwargs)
