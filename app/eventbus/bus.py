from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog

from app.eventbus.events import Event

logger = structlog.get_logger(__name__)

Listener = Callable[[Event], Awaitable[None]]
AsyncOrSyncListener = Callable[[Event], Awaitable[None] | None]


class EventBus:
    WILDCARD = "*"

    def __init__(self) -> None:
        self._listeners: dict[str, list[AsyncOrSyncListener]] = defaultdict(list)
        self._global_listeners: list[AsyncOrSyncListener] = []

    def on(self, event_name: str) -> Callable[[AsyncOrSyncListener], AsyncOrSyncListener]:
        def decorator(fn: AsyncOrSyncListener) -> AsyncOrSyncListener:
            self.register(event_name, fn)
            return fn

        return decorator

    def register(self, event_name: str, listener: AsyncOrSyncListener) -> None:
        self._listeners[event_name].append(listener)

    def unregister(self, event_name: str, listener: AsyncOrSyncListener) -> None:
        listeners = self._listeners.get(event_name)
        if listeners:
            with suppress(ValueError):
                listeners.remove(listener)

    async def emit(self, event: Event, *, timeout: float = 10.0) -> None:
        to_call: list[AsyncOrSyncListener] = []
        to_call.extend(self._global_listeners)
        to_call.extend(self._listeners.get(event.name, []))
        to_call.extend(self._listeners.get(self.WILDCARD, []))
        prefix = event.name.rsplit(".", 1)[0] if "." in event.name else event.name
        to_call.extend(self._listeners.get(f"{prefix}.*", []))

        if not to_call:
            return

        async def safe_call(listener: AsyncOrSyncListener) -> None:
            try:
                result = listener(event)
                if result is not None:
                    await asyncio.wait_for(result, timeout=timeout)
            except TimeoutError:
                logger.warning(
                    "eventbus.listener_timed_out",
                    event=event.name,
                    listener=getattr(listener, "__name__", None),
                )
            except Exception:
                logger.exception(
                    "eventbus.listener_failed",
                    event=event.name,
                    listener=getattr(listener, "__name__", None),
                )

        await asyncio.gather(*[safe_call(fn) for fn in to_call])

bus: EventBus = EventBus()
