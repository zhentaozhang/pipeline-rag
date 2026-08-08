import types

import pytest

import app.chat.memory_service as memory_service_module
from app.chat.memory_service import PersistentConversationMemoryService


class FakeSession:
    def __init__(self):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.memory_row = None

    async def execute(self, stmt):
        self.executed.append(stmt)
        return FakeResult(self.memory_row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class FakeStrategy:
    def __init__(self, memory_ctx=None):
        self.memory_ctx = memory_ctx
        self.load_calls = []
        self.save_calls = []

    async def load(self, conversation_id, db):
        self.load_calls.append(conversation_id)
        return self.memory_ctx

    async def save(self, **kwargs):
        self.save_calls.append(kwargs)


class TestPersistentMemoryService:
    @pytest.mark.asyncio
    async def test_load_delegates(self, monkeypatch):
        ctx = types.SimpleNamespace()
        monkeypatch.setattr(
            memory_service_module, "create_memory_strategy", lambda: FakeStrategy(ctx)
        )
        svc = PersistentConversationMemoryService(FakeSession())
        assert await svc.load("c1") is ctx

    @pytest.mark.asyncio
    async def test_save_delegates_and_raises(self, monkeypatch):
        strategy = FakeStrategy()
        monkeypatch.setattr(
            memory_service_module, "create_memory_strategy", lambda: strategy
        )
        svc = PersistentConversationMemoryService(FakeSession())
        await svc.save("c1", "q", "a", 1)
        assert strategy.save_calls[0]["question"] == "q"
        assert strategy.save_calls[0]["exchange_id"] == 1

    @pytest.mark.asyncio
    async def test_save_swallows_into_raise(self, monkeypatch):
        class BoomStrategy(FakeStrategy):
            async def save(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(
            memory_service_module, "create_memory_strategy", lambda: BoomStrategy()
        )
        svc = PersistentConversationMemoryService(FakeSession())
        with pytest.raises(RuntimeError):
            await svc.save("c1", "q", "a", 1)

    @pytest.mark.asyncio
    async def test_get_summary(self, monkeypatch):
        monkeypatch.setattr(
            memory_service_module, "create_memory_strategy", lambda: FakeStrategy()
        )
        db = FakeSession()
        db.memory_row = types.SimpleNamespace(summary_text="摘要")
        svc = PersistentConversationMemoryService(db)
        assert await svc.get_summary("c1") == "摘要"
        db.memory_row = None
        assert await svc.get_summary("c2") == ""

    @pytest.mark.asyncio
    async def test_delete_memory(self, monkeypatch):
        monkeypatch.setattr(
            memory_service_module, "create_memory_strategy", lambda: FakeStrategy()
        )
        db = FakeSession()
        svc = PersistentConversationMemoryService(db)
        await svc.delete_memory("c1")
        assert db.commits == 1

    @pytest.mark.asyncio
    async def test_rebuild_summary_uses_summary_strategy(self, monkeypatch):
        calls = []

        class FakeSummaryStrategy:
            async def compress_history(self, conversation_id, db):
                calls.append(conversation_id)

        monkeypatch.setattr(
            memory_service_module, "create_memory_strategy",
            lambda kind="default": FakeSummaryStrategy(),
        )
        monkeypatch.setattr(
            "app.chat.memory.SummaryCompressionStrategy", FakeSummaryStrategy
        )
        db = FakeSession()
        svc = PersistentConversationMemoryService(db)
        await svc.rebuild_summary("c1")
        assert calls == ["c1"]
        assert db.commits >= 1
