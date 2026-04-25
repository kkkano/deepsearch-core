"""测试 EventBus streaming 总线。"""

from __future__ import annotations

import asyncio

import pytest

from deepsearch_core.engine.events import Event, EventBus, EventType


@pytest.mark.asyncio
async def test_subscribe_receives_events():
    bus = EventBus()
    queue = bus.subscribe("run_x")

    event = Event(run_id="run_x", type=EventType.RUN_STARTED, payload={})
    await bus.publish(event)

    received = await asyncio.wait_for(queue.get(), timeout=1)
    assert received.type == EventType.RUN_STARTED


@pytest.mark.asyncio
async def test_unsubscribed_run_not_received():
    bus = EventBus()
    queue = bus.subscribe("run_x")

    event = Event(run_id="run_y", type=EventType.RUN_STARTED, payload={})
    await bus.publish(event)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.5)


@pytest.mark.asyncio
async def test_global_subscriber_receives_all():
    bus = EventBus()
    queue = bus.subscribe(None)  # global

    await bus.publish(Event(run_id="r1", type=EventType.RUN_STARTED, payload={}))
    await bus.publish(Event(run_id="r2", type=EventType.RUN_FINISHED, payload={}))

    e1 = await asyncio.wait_for(queue.get(), timeout=1)
    e2 = await asyncio.wait_for(queue.get(), timeout=1)
    assert {e1.run_id, e2.run_id} == {"r1", "r2"}


@pytest.mark.asyncio
async def test_close_sends_sentinel():
    bus = EventBus()
    queue = bus.subscribe("run_x")
    bus.close("run_x")
    sentinel = await asyncio.wait_for(queue.get(), timeout=1)
    assert sentinel is None
