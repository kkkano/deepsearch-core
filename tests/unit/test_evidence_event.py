"""测试 v0.1.3 MEDIUM: runner 在 state.evidence 增长时确实 emit EVIDENCE_FOUND。"""

from __future__ import annotations

import pytest

from deepsearch_core.engine.events import EventType
from deepsearch_core.engine.runner import END, GraphRunner
from deepsearch_core.engine.state import Evidence


@pytest.mark.asyncio
async def test_runner_emits_evidence_found_when_count_grows(store, basic_state):
    async def emit_evidence_node(state):
        new_evidence = [
            Evidence(sub_query_id="q1", url="https://a.com/1", title="A", snippet=""),
            Evidence(sub_query_id="q1", url="https://b.com/2", title="B", snippet=""),
            Evidence(sub_query_id="q1", url="https://c.com/3", title="C", snippet=""),
        ]
        return state.with_update(evidence=new_evidence), END

    runner = GraphRunner(nodes={"emit": emit_evidence_node}, store=store)
    await runner.run(basic_state, start_node="emit")

    events = list(store.replay(basic_state.run_id))
    evidence_events = [e for e in events if e.type == EventType.EVIDENCE_FOUND]
    assert len(evidence_events) == 1
    assert evidence_events[0].payload["added"] == 3
    assert evidence_events[0].payload["total"] == 3
    assert evidence_events[0].payload["node"] == "emit"


@pytest.mark.asyncio
async def test_runner_does_not_emit_when_evidence_unchanged(store, basic_state):
    async def noop_node(state):
        return state, END

    runner = GraphRunner(nodes={"n": noop_node}, store=store)
    await runner.run(basic_state, start_node="n")

    events = list(store.replay(basic_state.run_id))
    evidence_events = [e for e in events if e.type == EventType.EVIDENCE_FOUND]
    assert evidence_events == []
