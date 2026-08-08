import asyncio

import pytest

from app.eventbus.bus import EventBus
from app.eventbus.events import (
    ConversationStartedPayload,
    Event,
    ExecutionStartedPayload,
    RetrievalCompletedPayload,
    SafetyViolationPayload,
    StateTransitionPayload,
)


def make_event(name="chat.started", payload=None):
    return Event(name=name, payload=payload or ConversationStartedPayload(question="q", chat_mode="auto"))


class TestEventDefaults:
    def test_timestamp_and_metadata(self):
        e = make_event()
        assert e.timestamp is not None
        assert e.metadata == {}
        assert e.conversation_id is None
        assert e.exchange_id is None

    def test_payload_defaults(self):
        assert ConversationStartedPayload("q", "auto").chat_mode == "auto"
        assert RetrievalCompletedPayload("sq", 3, ["vector"]).evidence_count == 3
        assert SafetyViolationPayload("L1", "注入", 0.9, "txt").risk_score == 0.9
        assert StateTransitionPayload("a", "b", 10).elapsed_ms == 10
        assert ExecutionStartedPayload("RETRIEVAL", ["q1"]).sub_questions == ["q1"]


class TestEventBus:
    @pytest.mark.asyncio
    async def test_register_and_emit_async_listener(self):
        bus = EventBus()
        seen = []

        async def listener(event):
            seen.append(event.name)

        bus.register("chat.started", listener)
        await bus.emit(make_event())
        assert seen == ["chat.started"]

    @pytest.mark.asyncio
    async def test_sync_listener(self):
        bus = EventBus()
        seen = []
        bus.register("chat.started", lambda e: seen.append(e.name))
        await bus.emit(make_event())
        assert seen == ["chat.started"]

    @pytest.mark.asyncio
    async def test_on_decorator(self):
        bus = EventBus()
        seen = []

        @bus.on("chat.started")
        def listener(event):
            seen.append(event.payload.chat_mode)

        await bus.emit(make_event())
        assert seen == ["auto"]

    @pytest.mark.asyncio
    async def test_global_listener_receives_all(self):
        bus = EventBus()
        seen = []
        bus.register("*", lambda e: seen.append(e.name))
        bus.register("chat.started", lambda e: seen.append("specific"))
        await bus.emit(make_event())
        assert set(seen) == {"chat.started", "specific"}

    @pytest.mark.asyncio
    async def test_prefix_wildcard(self):
        bus = EventBus()
        seen = []
        bus.register("chat.*", lambda e: seen.append(e.name))
        await bus.emit(make_event("chat.started"))
        await bus.emit(make_event("other"))
        assert seen == ["chat.started"]

    @pytest.mark.asyncio
    async def test_unregister(self):
        bus = EventBus()
        seen = []

        def listener(event):
            seen.append(1)

        bus.register("chat.started", listener)
        bus.unregister("chat.started", listener)
        await bus.emit(make_event())
        assert seen == []

    @pytest.mark.asyncio
    async def test_exception_isolated(self):
        bus = EventBus()
        seen = []

        def bad(event):
            raise RuntimeError("boom")

        bus.register("chat.started", bad)
        bus.register("chat.started", lambda e: seen.append(1))
        await bus.emit(make_event())
        assert seen == [1]

    @pytest.mark.asyncio
    async def test_timeout(self):
        bus = EventBus()

        async def slow(event):
            await asyncio.sleep(5)

        bus.register("chat.started", slow)
        await bus.emit(make_event(), timeout=0.01)

    @pytest.mark.asyncio
    async def test_no_listeners_noop(self):
        await EventBus().emit(make_event())

    @pytest.mark.asyncio
    async def test_listeners_run_concurrently(self):
        bus = EventBus()
        order = []

        async def first(event):
            await asyncio.sleep(0.02)
            order.append("first")

        async def second(event):
            order.append("second")

        bus.register("chat.started", first)
        bus.register("chat.started", second)
        await bus.emit(make_event())
        assert order == ["second", "first"]
