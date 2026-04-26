"""测试 SQLite EventStore。"""

from __future__ import annotations

from datetime import datetime

from deepsearch_core.engine.events import Event, EventType
from deepsearch_core.engine.state import RunConfig, RunStatus, State


def test_create_and_get_run(store):
    state = State(config=RunConfig(goal="test goal"))
    store.create_run(state)

    run = store.get_run(state.run_id)
    assert run is not None
    assert run["goal"] == "test goal"
    assert run["status"] == RunStatus.PENDING.value


def test_update_run_status(store):
    state = State(config=RunConfig(goal="x"))
    store.create_run(state)
    store.update_run_status(state.run_id, "completed", datetime.utcnow())

    run = store.get_run(state.run_id)
    assert run["status"] == "completed"
    assert run["finished_at"] is not None


def test_append_and_replay_events(store):
    state = State(config=RunConfig(goal="x"))
    store.create_run(state)

    for i in range(5):
        event = Event(
            run_id=state.run_id,
            seq=i,
            type=EventType.NODE_STARTED,
            payload={"node": f"n{i}"},
        )
        store.append_event(event)

    events = list(store.replay(state.run_id))
    assert len(events) == 5
    assert all(e.type == EventType.NODE_STARTED for e in events)
    assert events[0].payload["node"] == "n0"


def test_query_cache_get_put(store):
    store.cache_put(
        query_hash="hash1",
        query="What is X",
        policy="general",
        response={"answer": "Y"},
        ttl_seconds=60,
    )
    cached = store.cache_get("hash1")
    assert cached is not None
    assert cached["answer"] == "Y"


def test_query_cache_miss(store):
    assert store.cache_get("nonexistent") is None
