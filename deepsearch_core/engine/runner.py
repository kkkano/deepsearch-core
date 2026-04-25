"""GraphRunner: 极简 graph 引擎，~200 行。

核心特性：
1. 节点是纯异步函数 (state) -> (state, next_node)
2. 每 tick 检查 steer，支持中断重规划
3. 所有状态变化落事件
4. 不依赖 LangGraph / LangChain
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from deepsearch_core.engine.events import Event, EventBus, EventType
from deepsearch_core.engine.state import RunStatus, State
from deepsearch_core.engine.steer import SteerCommand, SteerScope
from deepsearch_core.exceptions import DeepSearchError, TimeoutError_

if TYPE_CHECKING:
    from deepsearch_core.store.store import EventStore

logger = structlog.get_logger(__name__)

NodeFunc = Callable[[State], Awaitable[tuple[State, str]]]
END = "END"


class GraphRunner:
    """极简 graph runner。

    使用方式：
        runner = GraphRunner(nodes={"planner": planner_fn, ...}, store=store, bus=bus)
        final_state = await runner.run(initial_state, start_node="check_clarity")
    """

    def __init__(
        self,
        nodes: dict[str, NodeFunc],
        store: EventStore | None = None,
        bus: EventBus | None = None,
    ):
        self.nodes = nodes
        self.store = store
        self.bus = bus or EventBus()
        self._seq_counter: dict[str, int] = {}

    async def run(self, state: State, start_node: str = "check_clarity") -> State:
        """运行 graph 直到 END / 异常 / 超时。"""
        await self._emit(state.run_id, EventType.RUN_STARTED, {"goal": state.config.goal})
        if self.store:
            self.store.create_run(state)

        state = state.with_update(status=RunStatus.RUNNING, current_node=start_node)
        current = start_node

        try:
            while current != END:
                # ---- 检查点 1：节点开始前 check steer ----
                if state.config.enable_steer:
                    state, current_after_steer = await self._check_and_apply_steer(state, current, when="before")
                    current = current_after_steer

                if current == END:
                    break

                # ---- 检查超时 ----
                if state.elapsed_seconds() > state.config.timeout_seconds:
                    raise TimeoutError_(
                        f"Run {state.run_id} exceeded {state.config.timeout_seconds}s",
                        run_id=state.run_id,
                    )

                # ---- 执行节点 ----
                if current not in self.nodes:
                    raise DeepSearchError(f"Unknown node: {current}")

                logger.info("node_starting", run_id=state.run_id, node=current, step=state.step_count)
                await self._emit(state.run_id, EventType.NODE_STARTED, {"node": current, "step": state.step_count})

                node_fn = self.nodes[current]
                try:
                    new_state, next_node = await node_fn(state)
                except Exception as e:
                    logger.exception("node_error", run_id=state.run_id, node=current)
                    await self._emit(state.run_id, EventType.NODE_ERROR, {"node": current, "error": str(e)})
                    raise

                state = new_state.with_update(step_count=state.step_count + 1, current_node=next_node)
                await self._emit(
                    state.run_id,
                    EventType.NODE_COMPLETED,
                    {"node": current, "next": next_node, "step": state.step_count},
                )

                # ---- 检查点 2：节点完成后 check steer ----
                if state.config.enable_steer:
                    state, next_node = await self._check_and_apply_steer(state, next_node, when="after")

                current = next_node

            # ---- 正常结束 ----
            state = state.with_update(status=RunStatus.COMPLETED, finished_at=datetime.utcnow())
            await self._emit(state.run_id, EventType.RUN_FINISHED, {"status": "completed"})

        except TimeoutError_ as e:
            state = state.with_update(status=RunStatus.TIMEOUT, finished_at=datetime.utcnow(), last_error=str(e))
            await self._emit(state.run_id, EventType.RUN_FAILED, {"reason": "timeout", "error": str(e)})

        except Exception as e:
            state = state.with_update(status=RunStatus.FAILED, finished_at=datetime.utcnow(), last_error=str(e))
            await self._emit(state.run_id, EventType.RUN_FAILED, {"reason": "exception", "error": str(e)})

        finally:
            if self.store:
                self.store.update_run_status(state.run_id, state.status.value, state.finished_at)
            self.bus.close(state.run_id)

        return state

    async def _check_and_apply_steer(
        self, state: State, current: str, when: str
    ) -> tuple[State, str]:
        """检查 pending steer 并应用。返回 (新 state, 新 next_node)。"""
        if not self.store:
            return state, current

        steer = self.store.pop_pending_steer(state.run_id)
        if steer is None:
            return state, current

        await self._emit(
            state.run_id,
            EventType.STEER_RECEIVED,
            {"steer": steer.model_dump(mode="json"), "when": when, "current": current},
        )

        # current_step：注入到当前节点 prompt（state.steer_payload）
        if steer.scope == SteerScope.CURRENT_STEP:
            state = state.with_update(steer_payload={"content": steer.content, "scope": steer.scope.value})
            steer.mark_applied(current)
            await self._emit(state.run_id, EventType.STEER_APPLIED, {"scope": "current_step", "node": current})
            self.store.mark_steer_applied(steer)
            return state, current

        # global / next_step：跳转
        if steer.scope == SteerScope.GLOBAL:
            # 把 steer 内容追加到目标
            new_goal = f"{state.config.goal}\n\n[USER STEER]: {steer.content}"
            new_config = state.config.model_copy(update={"goal": new_goal})
            state = state.with_update(config=new_config, plan=None, interrupt_requested=True)
            steer.mark_applied("planner")
            await self._emit(state.run_id, EventType.STEER_APPLIED, {"scope": "global", "next": "planner"})
            self.store.mark_steer_applied(steer)
            return state, "planner"  # 跳回重规划

        if steer.scope == SteerScope.NEXT_STEP:
            state = state.with_update(steer_payload={"content": steer.content, "scope": steer.scope.value})
            steer.mark_applied(current)
            await self._emit(state.run_id, EventType.STEER_APPLIED, {"scope": "next_step", "node": current})
            self.store.mark_steer_applied(steer)
            return state, current

        return state, current

    async def _emit(self, run_id: str, type_: EventType, payload: dict) -> None:
        """统一事件发射：写 store + 推 bus。"""
        seq = self._seq_counter.get(run_id, 0)
        self._seq_counter[run_id] = seq + 1

        event = Event(run_id=run_id, type=type_, payload=payload, seq=seq)

        if self.store:
            try:
                self.store.append_event(event)
            except Exception:
                logger.exception("store_append_failed", run_id=run_id, event_type=type_.value)

        await self.bus.publish(event)

    async def stream_events(self, run_id: str):
        """订阅指定 run 的事件流（async iterator）。"""
        q = self.bus.subscribe(run_id)
        try:
            while True:
                event = await q.get()
                if event is None:  # sentinel
                    break
                yield event
        finally:
            self.bus.unsubscribe(run_id, q)
