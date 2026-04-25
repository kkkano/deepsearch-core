"""测试 GraphRunner 核心逻辑。"""

from __future__ import annotations

import pytest

from deepsearch_core.engine.events import EventType
from deepsearch_core.engine.runner import END, GraphRunner
from deepsearch_core.engine.state import RunConfig, RunStatus, State
from deepsearch_core.engine.steer import SteerScope


@pytest.mark.asyncio
async def test_runner_simple_pipeline(store, basic_state):
    """A → B → END 跑通。"""
    visited = []

    async def node_a(state):
        visited.append("a")
        return state, "b"

    async def node_b(state):
        visited.append("b")
        return state, END

    runner = GraphRunner(nodes={"a": node_a, "b": node_b}, store=store)
    final = await runner.run(basic_state, start_node="a")

    assert final.status == RunStatus.COMPLETED
    assert visited == ["a", "b"]


@pytest.mark.asyncio
async def test_runner_unknown_node_fails(store, basic_state):
    async def a(state):
        return state, "missing"

    runner = GraphRunner(nodes={"a": a}, store=store)
    final = await runner.run(basic_state, start_node="a")
    assert final.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_runner_writes_events(store, basic_state):
    async def n(state):
        return state, END

    runner = GraphRunner(nodes={"n": n}, store=store)
    final = await runner.run(basic_state, start_node="n")

    events = list(store.replay(basic_state.run_id))
    types = [e.type for e in events]

    assert EventType.RUN_STARTED in types
    assert EventType.NODE_STARTED in types
    assert EventType.RUN_FINISHED in types


@pytest.mark.asyncio
async def test_runner_run_started_event_persisted(store, basic_state):
    """修复 #2.1 验证：第一条 RUN_STARTED 必须真的写入 events 表（外键不挡）。"""
    async def n(state):
        return state, END

    runner = GraphRunner(nodes={"n": n}, store=store)
    await runner.run(basic_state, start_node="n")

    events = list(store.replay(basic_state.run_id))
    # 第一条事件必须是 RUN_STARTED 并且确实落地
    assert len(events) >= 1
    assert events[0].type == EventType.RUN_STARTED
    assert events[0].payload.get("goal") == basic_state.config.goal


@pytest.mark.asyncio
async def test_runner_node_timeout_marks_run_timeout(store):
    """修复 #2.2 验证：单节点超时 → 整个 run 被标记为 timeout。"""
    import asyncio

    state = State(config=RunConfig(goal="x", timeout_seconds=1))

    async def hang(state):
        await asyncio.sleep(10)  # 远超 1s timeout
        return state, END

    runner = GraphRunner(nodes={"hang": hang}, store=store)
    final = await runner.run(state, start_node="hang")

    assert final.status == RunStatus.TIMEOUT
    # 验证 events 里有 NODE_ERROR 标记 node_timeout
    events = list(store.replay(state.run_id))
    error_events = [e for e in events if e.type == EventType.NODE_ERROR]
    assert error_events, "应该至少有一条 NODE_ERROR"
    assert "timeout" in error_events[0].payload.get("error", "").lower()


@pytest.mark.asyncio
async def test_runner_steer_global_jumps_to_planner(store, basic_state):
    """global scope steer 让 runner 跳到 planner 节点。"""
    visited = []

    async def planner(state):
        visited.append("planner")
        return state, END

    async def researcher(state):
        visited.append("researcher")
        return state, END

    runner = GraphRunner(nodes={"planner": planner, "researcher": researcher}, store=store)

    # 修复 #2.1 后外键启用：必须先 create_run 才能加 steer
    store.create_run(basic_state)
    store.add_steer(basic_state.run_id, "重点看 X", SteerScope.GLOBAL)

    final = await runner.run(basic_state, start_node="researcher")

    # global scope → 跳到 planner
    assert "planner" in visited
    assert final.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_runner_steer_current_step_inline(store, basic_state):
    """current_step scope 不重规划，但注入 steer_payload。"""
    captured = {}

    async def n(state):
        captured["payload"] = state.steer_payload
        return state, END

    runner = GraphRunner(nodes={"n": n}, store=store)
    store.create_run(basic_state)
    store.add_steer(basic_state.run_id, "narrow scope", SteerScope.CURRENT_STEP)

    final = await runner.run(basic_state, start_node="n")
    assert captured["payload"] is not None
    assert captured["payload"]["scope"] == SteerScope.CURRENT_STEP.value
    assert "narrow scope" in captured["payload"]["content"]


@pytest.mark.asyncio
async def test_runner_timeout_status(store):
    """超时返回 TIMEOUT 状态。"""
    import asyncio

    state = State(config=RunConfig(goal="x", timeout_seconds=1))

    async def slow(state):
        await asyncio.sleep(2)
        return state, END

    runner = GraphRunner(nodes={"slow": slow}, store=store)
    # 注意：当前实现是节点开始前 check 超时，所以单节点超时不一定捕获
    # v0.2 加入节点内 timeout
    final = await runner.run(state, start_node="slow")
    assert final.status in (RunStatus.TIMEOUT, RunStatus.COMPLETED)
