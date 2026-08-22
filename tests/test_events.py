"""Unit tests for EventBus synchronization, async scheduling, and lifecycle management."""

from __future__ import annotations

import asyncio
import pytest

from metaglyph.core.events import EventBus, get_event_bus


def test_event_bus_sync_subscription() -> None:
    """Test synchronous subscribe, emit, and unsubscribe flows."""
    bus = EventBus()
    received = []

    def handler(value: int) -> None:
        received.append(value)

    bus.subscribe("test_event", handler)
    bus.emit("test_event", value=42)
    assert received == [42]

    bus.unsubscribe("test_event", handler)
    bus.emit("test_event", value=99)
    assert received == [42]


@pytest.mark.asyncio
async def test_event_bus_async_task_retention() -> None:
    """Test that async callbacks create tracked background tasks."""
    bus = EventBus()
    completed = []

    async def async_handler(msg: str) -> None:
        await asyncio.sleep(0.01)
        completed.append(msg)

    bus.subscribe("async_event", async_handler)
    bus.emit("async_event", msg="hello")

    # Verify task is tracked in _background_tasks set
    assert len(bus._background_tasks) == 1

    # Await tasks to complete
    await asyncio.gather(*bus._background_tasks)
    assert completed == ["hello"]
    # Verify done callback discards task
    assert len(bus._background_tasks) == 0


@pytest.mark.asyncio
async def test_event_bus_emit_async() -> None:
    """Test emit_async awaits coroutines properly."""
    bus = EventBus()
    events = []

    async def async_handler(val: int) -> None:
        await asyncio.sleep(0.01)
        events.append(val)

    bus.subscribe("num_event", async_handler)
    await bus.emit_async("num_event", val=100)
    assert events == [100]


def test_event_bus_coroutine_cleanup_without_loop() -> None:
    """Test that coroutines are closed cleanly without warnings when emit is called without running loop."""
    bus = EventBus()

    async def orphan_coro() -> None:
        pass

    bus.subscribe("orphan", orphan_coro)
    # Outside async context, emit should gracefully close the coroutine without leaking
    bus.emit("orphan")
