"""Event dispatcher and signaling mechanisms."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine


class EventBus:
    """Async & sync event bus for decoupled communication across modules."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        """Subscribe a handler to an event."""
        if callback not in self._listeners[event_name]:
            self._listeners[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        """Unsubscribe a handler from an event."""
        if callback in self._listeners[event_name]:
            self._listeners[event_name].remove(callback)

    def emit(self, event_name: str, **kwargs: Any) -> None:
        """Emit an event to all subscribers synchronously (scheduling coroutines if async)."""
        for callback in list(self._listeners[event_name]):
            try:
                res = callback(**kwargs)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as exc:
                import logging
                logging.getLogger("metaglyph.events").error(
                    "Error executing listener for '%s': %s", event_name, exc, exc_info=True
                )

    async def emit_async(self, event_name: str, **kwargs: Any) -> None:
        """Emit an event and await all asynchronous listeners."""
        for callback in list(self._listeners[event_name]):
            try:
                res = callback(**kwargs)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                import logging
                logging.getLogger("metaglyph.events").error(
                    "Error executing async listener for '%s': %s", event_name, exc, exc_info=True
                )


_global_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Retrieve the global EventBus instance."""
    return _global_event_bus
