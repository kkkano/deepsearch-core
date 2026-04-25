"""测试核心 state 数据模型。"""

from __future__ import annotations

import pytest

from deepsearch_core.engine.state import (
    Plan,
    RunConfig,
    RunStatus,
    State,
    SubQuery,
    TokenUsage,
)


def test_state_default_run_id():
    state = State(config=RunConfig(goal="test"))
    assert state.run_id.startswith("run_")
    assert len(state.run_id) > 4


def test_state_immutable_with_update():
    state = State(config=RunConfig(goal="test"))
    new_state = state.with_update(status=RunStatus.RUNNING, step_count=5)

    assert state.status == RunStatus.PENDING
    assert state.step_count == 0
    assert new_state.status == RunStatus.RUNNING
    assert new_state.step_count == 5
    assert new_state.run_id == state.run_id


def test_state_elapsed_seconds():
    state = State(config=RunConfig(goal="test"))
    assert state.elapsed_seconds() >= 0


def test_token_usage_add():
    usage = TokenUsage()
    usage.add(prompt=100, completion=50, cached=10)
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 50
    assert usage.cached_tokens == 10
    assert usage.total_tokens == 150


def test_subquery_unique_ids():
    sq1 = SubQuery(text="q1")
    sq2 = SubQuery(text="q2")
    assert sq1.id != sq2.id


def test_plan_revision_default():
    plan = Plan()
    assert plan.revision == 1
    assert plan.sub_queries == []


def test_run_config_defaults():
    cfg = RunConfig(goal="hello")
    assert cfg.depth == 3
    assert cfg.max_agents == 4
    assert cfg.policy == "general"
    assert cfg.enable_steer is True
