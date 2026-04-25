"""测试 Steer 中断机制。"""

from __future__ import annotations

import pytest

from deepsearch_core.engine.steer import SteerCommand, SteerScope


def test_steer_default_scope():
    cmd = SteerCommand(run_id="run_123", content="test")
    assert cmd.scope == SteerScope.GLOBAL
    assert cmd.applied is False


def test_steer_unique_cmd_id():
    a = SteerCommand(run_id="run_x", content="a")
    b = SteerCommand(run_id="run_x", content="b")
    assert a.cmd_id != b.cmd_id


def test_steer_mark_applied():
    cmd = SteerCommand(run_id="run_x", content="hello")
    cmd.mark_applied("planner")
    assert cmd.applied is True
    assert cmd.applied_at is not None
    assert cmd.applied_at_step == "planner"


def test_steer_to_prompt_injection():
    cmd = SteerCommand(run_id="r", content="重点看 X")
    s = cmd.to_prompt_injection()
    assert "User mid-flight directive" in s
    assert "重点看 X" in s


def _seed_run(store, run_id: str) -> None:
    """test helper: 创建一个 run 行，让外键约束满足。"""
    from deepsearch_core.engine.state import RunConfig, State

    state = State(run_id=run_id, config=RunConfig(goal=f"goal-{run_id}"))
    store.create_run(state)


def test_store_add_pop_steer(store):
    _seed_run(store, "run_a")
    cmd = store.add_steer("run_a", "redirect please", SteerScope.CURRENT_STEP)
    assert cmd.run_id == "run_a"

    popped = store.pop_pending_steer("run_a")
    assert popped is not None
    assert popped.content == "redirect please"
    assert popped.scope == SteerScope.CURRENT_STEP


def test_store_pop_returns_none_when_empty(store):
    assert store.pop_pending_steer("nonexistent") is None


def test_store_mark_applied_then_no_pop(store):
    _seed_run(store, "run_b")
    cmd = store.add_steer("run_b", "test")
    popped = store.pop_pending_steer("run_b")
    assert popped is not None

    popped.mark_applied("planner")
    store.mark_steer_applied(popped)

    # 再 pop 不应再返回
    assert store.pop_pending_steer("run_b") is None
