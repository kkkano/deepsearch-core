"""测试 RunManager 跨适配统一生命周期。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from deepsearch_core.engine.manager import RunManager
from deepsearch_core.engine.runner import END
from deepsearch_core.engine.state import (
    Citation,
    Report,
    RunConfig,
    RunStatus,
    State,
)


class _FakeDS:
    """最小可用 DeepSearch 替身，仅提供 manager 需要的属性。"""

    def __init__(self, store, runner_factory):
        self.store = store
        self._runner_factory = runner_factory
        from deepsearch_core.config import GlobalConfig
        self.config = GlobalConfig()

    def _build_context(self, policy):  # 不使用，但 manager 调
        return None

    def _build_runner(self, ctx):
        return self._runner_factory()


@pytest.mark.asyncio
async def test_manager_start_poll_returns_real_report(store):
    """start → poll → 拿到真实 report（不能是占位）。"""
    from deepsearch_core.engine.runner import GraphRunner

    async def report_node(state):
        report = Report(
            summary="test summary",
            body_markdown="# Real Report\n\nThis is the actual content.",
            citations=[Citation(index=1, url="https://x.com", title="X", snippet="...")],
            confidence=0.9,
        )
        return state.with_update(report=report), END

    def make_runner():
        return GraphRunner(nodes={"report": report_node, "check_clarity": report_node}, store=store)

    fake_ds = _FakeDS(store, make_runner)
    manager = RunManager(fake_ds)  # type: ignore

    payload = await manager.start("test query")
    task_id = payload["task_id"]
    assert payload["status"] == "running"

    # poll 直到完成
    poll = await manager.poll(task_id, wait_seconds=5)
    assert poll["still_running"] is False
    assert poll["status"] == "completed"
    assert "Real Report" in poll["final_report"]
    assert poll["citations"]
    assert poll["citations"][0]["url"] == "https://x.com"


@pytest.mark.asyncio
async def test_manager_cancel_sets_cancelled_status(store):
    """cancel 后 store 状态必须是 cancelled。"""
    from deepsearch_core.engine.runner import GraphRunner

    started = asyncio.Event()

    async def slow_node(state):
        started.set()
        await asyncio.sleep(10)  # 模拟长任务
        return state, END

    def make_runner():
        return GraphRunner(nodes={"slow": slow_node, "check_clarity": slow_node}, store=store)

    fake_ds = _FakeDS(store, make_runner)
    manager = RunManager(fake_ds)  # type: ignore

    payload = await manager.start("slow query")
    task_id = payload["task_id"]

    # 等任务真正起来再 cancel（避免 task 还没开始就被 cancel）
    await asyncio.wait_for(started.wait(), timeout=2)
    await manager.cancel(task_id)

    run = store.get_run(task_id)
    assert run is not None
    assert run["status"] == RunStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_manager_poll_unknown_task_raises(store):
    fake_ds = _FakeDS(store, lambda: None)
    manager = RunManager(fake_ds)  # type: ignore

    from deepsearch_core.exceptions import TaskNotFoundError
    with pytest.raises(TaskNotFoundError):
        await manager.poll("nonexistent_task_id", wait_seconds=1)
