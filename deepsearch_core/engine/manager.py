"""RunManager: 统一任务生命周期。

所有适配层（HTTP / MCP / CLI / SDK）共享同一个 manager 实例，
避免「HTTP 启动的任务 MCP 看不到」这类跨适配状态不一致。

提供：
    - start(query, ...) → task_id（异步启动）
    - poll(task_id, wait_seconds) → status + 部分结果（长轮询）
    - cancel(task_id) → 取消并落 RUN_CANCELLED
    - result(task_id) → 已持久化的最终结果（含 report/evidence/critic）
    - events(task_id) → 完整事件流
    - steer(task_id, content, scope)
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog

from deepsearch_core.engine.runner import GraphRunner
from deepsearch_core.engine.state import RunConfig, RunStatus, State
from deepsearch_core.engine.steer import SteerCommand, SteerScope
from deepsearch_core.exceptions import (
    TaskAlreadyFinishedError,
    TaskNotFoundError,
)

if TYPE_CHECKING:
    from deepsearch_core.facade import DeepSearch

logger = structlog.get_logger(__name__)

# Long-poll 上限（避开 MCP 60s timeout，留 buffer）
_MAX_POLL_SECONDS = 25


class RunManager:
    """跨适配层共享的任务生命周期管理器。"""

    def __init__(self, ds: DeepSearch):
        self.ds = ds
        # task_id → asyncio.Task（in-process 句柄）
        self._tasks: dict[str, asyncio.Task[State]] = {}
        # task_id → asyncio.Event（completion signal，poll 用）
        self._completion_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    async def start(
        self,
        query: str,
        depth: int = 3,
        policy: str | dict = "general",
        max_agents: int | None = None,
        timeout_seconds: int | None = None,
        enable_steer: bool = True,
    ) -> dict[str, Any]:
        """异步启动一个 deep search task，立即返回。"""
        engine_cfg = self.ds.config.engine
        config = RunConfig(
            goal=query,
            depth=depth,
            max_agents=max_agents or engine_cfg.max_agents_fan_out,
            max_steps_per_agent=engine_cfg.max_steps_per_research,
            policy=policy if not isinstance(policy, dict) else policy,
            timeout_seconds=timeout_seconds or engine_cfg.task_timeout_seconds,
            enable_steer=enable_steer,
        )
        state = State(config=config)
        ctx = self.ds._build_context(policy)
        runner = self.ds._build_runner(ctx)

        completion = asyncio.Event()
        run_id = state.run_id
        self._completion_events[run_id] = completion

        async def _wrapped_run() -> State:
            try:
                return await runner.run(state, start_node="check_clarity")
            finally:
                completion.set()

        task = asyncio.create_task(_wrapped_run(), name=f"run-{run_id}")
        self._tasks[run_id] = task

        # ---- 修复 HIGH-3：任务结束自动清理，无 poll 也不泄漏 ----
        def _on_done(_t: asyncio.Task) -> None:
            self._tasks.pop(run_id, None)
            self._completion_events.pop(run_id, None)
            # 吞掉 task.exception() 防止 "task exception was never retrieved" warning
            try:
                _t.exception()
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                pass

        task.add_done_callback(_on_done)

        return {
            "task_id": run_id,
            "status": "running",
            "eta_seconds": 30 + depth * 15,
            "poll_with": "poll",
            "steer_with": "steer",
            "resource_uri": f"deepsearch://task/{run_id}",
        }

    # ------------------------------------------------------------------
    # poll
    # ------------------------------------------------------------------

    async def poll(self, task_id: str, wait_seconds: int = _MAX_POLL_SECONDS) -> dict[str, Any]:
        """长轮询。最多等 wait_seconds（上限 25s 避开 MCP 60s 超时）。"""
        wait = min(max(0, wait_seconds), _MAX_POLL_SECONDS)
        completion = self._completion_events.get(task_id)

        if completion is None:
            # 任务可能已完成且被回收，从 store 读
            persisted = self.ds.store.get_run_result(task_id)
            run = self.ds.store.get_run(task_id)
            if run is None:
                raise TaskNotFoundError(f"No task with id {task_id}")
            return self._build_completed_payload(task_id, run, persisted)

        if completion.is_set():
            return self._fetch_completed(task_id)

        # 等 wait 秒，超时返回 partial
        try:
            await asyncio.wait_for(completion.wait(), timeout=wait)
        except asyncio.TimeoutError:
            return self._build_partial_payload(task_id)

        return self._fetch_completed(task_id)

    def _fetch_completed(self, task_id: str) -> dict[str, Any]:
        run = self.ds.store.get_run(task_id)
        persisted = self.ds.store.get_run_result(task_id)
        # in-process 引用由 add_done_callback 自动清理（修复 HIGH-3）
        return self._build_completed_payload(task_id, run, persisted)

    def _build_partial_payload(self, task_id: str) -> dict[str, Any]:
        events = list(self.ds.store.replay(task_id))
        last_event = events[-1] if events else None
        evidence_count = sum(1 for e in events if e.type.value == "evidence_found")
        return {
            "task_id": task_id,
            "status": "running",
            "current_step": (last_event.payload.get("node") if last_event else "unknown"),
            "progress": min(0.95, len(events) / 30.0),
            "evidence_count": evidence_count,
            "still_running": True,
        }

    def _build_completed_payload(self, task_id: str, run: dict | None, persisted: dict | None) -> dict[str, Any]:
        if not run:
            return {"task_id": task_id, "status": "unknown", "still_running": False}
        report_md = ""
        citations: list[dict] = []
        critic = None
        token_usage: dict | None = None
        if persisted:
            report = persisted.get("report") or {}
            report_md = report.get("body_markdown") or ""
            citations = (report.get("citations") if report else []) or []
            critic = persisted.get("critic")
            token_usage = persisted.get("token_usage")
        return {
            "task_id": task_id,
            "status": run.get("status", "unknown"),
            "final_report": report_md,
            "citations": citations,
            "critic": critic,
            "token_usage": token_usage,
            "error": (persisted or {}).get("error") or run.get("status") == "failed",
            "still_running": False,
        }

    # ------------------------------------------------------------------
    # cancel
    # ------------------------------------------------------------------

    async def cancel(self, task_id: str) -> dict[str, Any]:
        """取消任务。

        ---- 修复 MEDIUM-4：返回区分 4 种情况 ----
        - cancelled=True, status=cancelled         → 真的取消了
        - cancelled=False, reason=not_found        → task_id 不存在
        - cancelled=False, reason=already_finished → 任务已经完成/失败/超时
        - cancelled=False, reason=no_in_flight     → store 有记录但 in-process 句柄丢失
        """
        task = self._tasks.get(task_id)

        if task is None:
            run = self.ds.store.get_run(task_id)
            if run is None:
                return {"cancelled": False, "reason": "not_found", "task_id": task_id}
            if run.get("finished_at"):
                return {
                    "cancelled": False,
                    "reason": "already_finished",
                    "status": run.get("status"),
                    "task_id": task_id,
                }
            return {"cancelled": False, "reason": "no_in_flight", "task_id": task_id}

        if task.done():
            return {
                "cancelled": False,
                "reason": "already_finished",
                "task_id": task_id,
            }

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("cancel_swallowed", task_id=task_id)
        # add_done_callback 已自动清理 _tasks/_completion_events
        return {"cancelled": True, "task_id": task_id, "status": "cancelled"}

    # ------------------------------------------------------------------
    # steer
    # ------------------------------------------------------------------

    def steer(self, task_id: str, content: str, scope: str = "global") -> SteerCommand:
        run = self.ds.store.get_run(task_id)
        if run and run.get("status") not in (None, "running", "pending"):
            raise TaskAlreadyFinishedError(
                f"Task {task_id} is already {run.get('status')}",
                task_id=task_id,
            )
        return self.ds.store.add_steer(task_id, content, SteerScope(scope))

    # ------------------------------------------------------------------
    # result / events
    # ------------------------------------------------------------------

    def result(self, task_id: str) -> dict[str, Any] | None:
        return self.ds.store.get_run_result(task_id)

    def events(self, task_id: str) -> list:
        return list(self.ds.store.replay(task_id))

    def list_running(self) -> list[str]:
        return [tid for tid, t in self._tasks.items() if not t.done()]

    async def aclose(self) -> None:
        """优雅关闭：取消所有 in-flight 任务。"""
        for task_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._tasks.clear()
        self._completion_events.clear()
