"""测试 v0.1.3 HIGH 竞态修复：start() 返回时 durable state 必须已经存在。

reviewer 指出的三种竞态：
1. start → 立刻 steer → 不能触发外键失败
2. start → 立刻 cancel → store 必须有 cancelled 记录（审计链）
3. start 返回后 GET /v1/runs/{id} 必须立刻可查
"""

from __future__ import annotations

import asyncio

import pytest

from deepsearch_core.engine.manager import RunManager
from deepsearch_core.engine.runner import END
from deepsearch_core.engine.state import RunStatus


class _FakeDS:
    def __init__(self, store, runner_factory):
        self.store = store
        self._runner_factory = runner_factory
        from deepsearch_core.config import GlobalConfig

        self.config = GlobalConfig()

    def _build_context(self, policy):
        return None

    def _build_runner(self, ctx):
        return self._runner_factory()


@pytest.mark.asyncio
async def test_start_then_immediate_steer_is_queued(store):
    """start 后立刻 steer 不能触发 SQLite FK IntegrityError。"""
    from deepsearch_core.engine.runner import GraphRunner

    started = asyncio.Event()

    async def slow(state):
        started.set()
        await asyncio.sleep(2)
        return state, END

    def make_runner():
        return GraphRunner(nodes={"slow": slow, "check_clarity": slow}, store=store)

    fake_ds = _FakeDS(store, make_runner)
    manager = RunManager(fake_ds)  # type: ignore

    payload = await manager.start("query")
    task_id = payload["task_id"]

    # 立刻 steer（runner.run 可能还没开始执行）
    cmd = manager.steer(task_id, "narrow scope", scope="current_step")
    assert cmd.cmd_id is not None
    assert cmd.run_id == task_id

    # 必须能从 store 看到 steer
    pending = store.list_steer(task_id)
    assert len(pending) == 1
    assert pending[0]["content"] == "narrow scope"

    # 收尾
    await manager.cancel(task_id)


@pytest.mark.asyncio
async def test_start_then_immediate_cancel_persists_cancelled(store):
    """start 后立刻 cancel 必须在 store 留下 cancelled 记录。"""
    from deepsearch_core.engine.runner import GraphRunner

    async def slow(state):
        await asyncio.sleep(2)
        return state, END

    def make_runner():
        return GraphRunner(nodes={"slow": slow, "check_clarity": slow}, store=store)

    fake_ds = _FakeDS(store, make_runner)
    manager = RunManager(fake_ds)  # type: ignore

    payload = await manager.start("query")
    task_id = payload["task_id"]

    # 立刻 cancel —— task 可能还没真正被调度
    res = await manager.cancel(task_id)
    assert res["cancelled"] is True

    # store 里必须有 run 行，且状态已经收尾为 cancelled / failed / completed
    run = store.get_run(task_id)
    assert run is not None, "审计链断裂：store 应当有 run 行"
    assert run["status"] == RunStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_start_returns_only_after_run_is_queryable(store):
    """start 返回 task_id 时，GET /v1/runs/{id} 必须立刻可查（不能 404）。"""
    from deepsearch_core.engine.runner import GraphRunner

    async def slow(state):
        await asyncio.sleep(0.5)
        return state, END

    def make_runner():
        return GraphRunner(nodes={"slow": slow, "check_clarity": slow}, store=store)

    fake_ds = _FakeDS(store, make_runner)
    manager = RunManager(fake_ds)  # type: ignore

    payload = await manager.start("query")
    task_id = payload["task_id"]

    # 立即 get_run 必须返回非 None
    run = store.get_run(task_id)
    assert run is not None, "start() 必须在返回前同步落 store"
    assert run["status"] == RunStatus.RUNNING.value
    assert run["goal"] == "query"

    # 收尾
    await manager.cancel(task_id)


@pytest.mark.asyncio
async def test_create_run_idempotent_does_not_drop_steer(store):
    """create_run 现在用 INSERT OR IGNORE + UPDATE：重复调用不能删除已有 steer 子表数据。"""
    from deepsearch_core.engine.state import RunConfig, State
    from deepsearch_core.engine.steer import SteerScope

    state = State(config=RunConfig(goal="g"))
    # 第一次创建
    store.create_run(state)
    # 加 steer
    store.add_steer(state.run_id, "command", SteerScope.GLOBAL)
    pending_before = store.list_steer(state.run_id)
    assert len(pending_before) == 1

    # 模拟 manager.start + runner.run 双重调用
    state2 = state.with_update(status=__import__("deepsearch_core.engine.state", fromlist=["RunStatus"]).RunStatus.RUNNING)
    store.create_run(state2)

    # steer 必须保留（旧 INSERT OR REPLACE 会因 FK 级联删掉它）
    pending_after = store.list_steer(state.run_id)
    assert len(pending_after) == 1, "create_run 不能删掉已有 steer 子表数据"
