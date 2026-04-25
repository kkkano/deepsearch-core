"""事件类型 + EventBus（streaming 总线）。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    # 生命周期
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"

    # 节点
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_ERROR = "node_error"

    # LLM
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    LLM_TOKEN_STREAM = "llm_token_stream"

    # Tool / Search
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    SEARCH_QUERY_ISSUED = "search_query_issued"
    SEARCH_RESULTS_RECEIVED = "search_results_received"

    # State / Quality
    STATE_CHANGE = "state_change"
    EVIDENCE_FOUND = "evidence_found"
    CITATION_ADDED = "citation_added"
    PARTIAL_RESULT = "partial_result"

    # Steer
    STEER_RECEIVED = "steer_received"
    STEER_APPLIED = "steer_applied"
    STEER_REJECTED = "steer_rejected"


class Event(BaseModel):
    """单条事件。"""

    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    run_id: str
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    seq: int = 0  # 同 run 内的递增序号


class EventBus:
    """streaming 总线：node → bus → adapters → user。

    每个 adapter（HTTP / WS / MCP / CLI）调用 subscribe() 拿到一个 Queue，
    然后 async for event in queue 拉取。
    """

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._global_subscribers: list[asyncio.Queue] = []

    def subscribe(self, run_id: str | None = None) -> asyncio.Queue:
        """订阅指定 run 的事件，或所有事件 (run_id=None)。"""
        q: asyncio.Queue = asyncio.Queue()
        if run_id is None:
            self._global_subscribers.append(q)
        else:
            self._subscribers.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str | None, queue: asyncio.Queue) -> None:
        if run_id is None:
            if queue in self._global_subscribers:
                self._global_subscribers.remove(queue)
        elif run_id in self._subscribers and queue in self._subscribers[run_id]:
            self._subscribers[run_id].remove(queue)

    async def publish(self, event: Event) -> None:
        """非阻塞地把 event 推给所有订阅者。"""
        targets = list(self._global_subscribers)
        targets.extend(self._subscribers.get(event.run_id, []))
        for q in targets:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 慢消费者，丢弃 (TODO: 可选 backpressure)
                pass

    def close(self, run_id: str) -> None:
        """运行结束时通知 run 内订阅者结束。"""
        for q in self._subscribers.get(run_id, []):
            q.put_nowait(None)  # sentinel
        self._subscribers.pop(run_id, None)
