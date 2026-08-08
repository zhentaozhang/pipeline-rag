"""ConversationArchiveStore 单元测试：用最小 FakeDB 验证控制流与字段组装（无真实 DB）。"""

import pytest

from app.chat.store import ConversationArchiveStore
from app.chat.task_info import ChatRuntimeRegistry, ChatTaskInfo
from app.db.models.conversation import ConversationExchange, ConversationSession


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, execute_results=None, scalar_results=None):
        self._execute_results = list(execute_results or [])
        self._scalar_results = list(scalar_results or [])
        self.executed: list = []
        self.added: list = []
        self.flushed = 0
        self.committed = 0

    async def execute(self, stmt):
        self.executed.append(stmt)
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult([])

    async def scalar(self, stmt):
        self.executed.append(stmt)
        if self._scalar_results:
            return self._scalar_results.pop(0)
        return None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.committed += 1


@pytest.fixture(autouse=True)
def _clean_registry():
    ChatRuntimeRegistry._registry.clear()
    yield
    ChatRuntimeRegistry._registry.clear()


def _session(conversation_id: str = "c1", title: str = "t") -> ConversationSession:
    return ConversationSession(
        id=1, conversation_id=conversation_id, title=title, created_at=None
    )


def _exchange(eid: int = 1, conversation_id: str = "c1") -> ConversationExchange:
    return ConversationExchange(
        id=eid,
        conversation_id=conversation_id,
        question="q",
        answer="",
        created_at=None,
    )


class TestFindOrCreateSession:
    async def test_creates_new_session_with_truncated_title(self):
        db = FakeDB(execute_results=[FakeResult([])])
        store = ConversationArchiveStore(db)
        session, created = await store.find_or_create_session("c1", "长" * 100)
        assert created is True
        assert session.conversation_id == "c1"
        assert len(session.title) == 50
        assert db.added == [session]
        assert db.flushed == 1

    async def test_returns_existing_session(self):
        existing = _session()
        db = FakeDB(execute_results=[FakeResult([existing])])
        store = ConversationArchiveStore(db)
        session, created = await store.find_or_create_session("c1", "new")
        assert session is existing
        assert created is False
        assert db.added == []


class TestGetSession:
    async def test_hit(self):
        existing = _session()
        db = FakeDB(execute_results=[FakeResult([existing])])
        assert await ConversationArchiveStore(db).get_session("c1") is existing

    async def test_miss(self):
        db = FakeDB(execute_results=[FakeResult([])])
        assert await ConversationArchiveStore(db).get_session("c1") is None


class TestStartExchange:
    async def test_adds_and_commits(self):
        db = FakeDB()
        store = ConversationArchiveStore(db)
        await store.start_exchange(10, "c1", 1, "问题", execution_mode="rag")
        assert len(db.added) == 1
        assert db.added[0].id == 10
        assert db.added[0].execution_mode == "rag"
        assert db.committed == 1

    async def test_empty_execution_mode_becomes_none(self):
        db = FakeDB()
        await ConversationArchiveStore(db).start_exchange(10, "c1", 1, "q", "")
        assert db.added[0].execution_mode is None


class TestCompleteExchange:
    async def test_early_return_when_exchange_missing(self):
        db = FakeDB(scalar_results=[None])
        store = ConversationArchiveStore(db)
        await store.complete_exchange(99, "c1", "answer")
        assert db.executed == [db.executed[0]]
        assert db.committed == 0

    async def test_updates_core_fields(self):
        db = FakeDB(scalar_results=[_exchange(1, "c1")])
        store = ConversationArchiveStore(db)
        await store.complete_exchange(
            1, "c1", "最终答案", tokens_used=42, turn_status=2,
            first_response_time_ms=100, total_response_time_ms=500,
        )
        assert db.committed == 1
        assert len(db.executed) == 3

    async def test_serializes_json_fields(self):

        db = FakeDB(scalar_results=[_exchange(1, "c1")])
        store = ConversationArchiveStore(db)
        await store.complete_exchange(
            1, "c1", "a", references=[{"id": 1}], thinking_steps=["s1"], used_tools=["t1"]
        )
        updates = [e for e in db.executed if e.__class__.__name__ == "Update"]
        assert len(updates) == 2

    async def test_extracts_execution_mode_from_debug_trace(self):
        db = FakeDB(scalar_results=[_exchange(1, "c1")])
        store = ConversationArchiveStore(db)
        await store.complete_exchange(1, "c1", "a", debug_trace={"execution_mode": "multi_agent"})
        assert db.committed == 1

    async def test_skips_error_message_when_empty(self):
        db = FakeDB(scalar_results=[_exchange(1, "c1")])
        await ConversationArchiveStore(db).complete_exchange(1, "c1", "a")
        assert db.committed == 1

    async def test_error_message_written_when_failed(self):
        db = FakeDB(scalar_results=[_exchange(1, "c1")])
        await ConversationArchiveStore(db).complete_exchange(1, "c1", "a", error_message="boom")
        assert db.committed == 1


class TestUpdateAndDelete:
    async def test_update_session_title_commits(self):
        db = FakeDB()
        await ConversationArchiveStore(db).update_session_title("c1", "新标题")
        assert db.committed == 1

    async def test_delete_session_cascade_commits(self):
        db = FakeDB()
        await ConversationArchiveStore(db).delete_session_cascade("c1")
        assert db.committed == 1
        assert len(db.executed) == 3


class TestListExchanges:
    async def test_returns_rows_and_total(self):
        rows = [_exchange(1), _exchange(2)]
        db = FakeDB(
            execute_results=[FakeResult([2]), FakeResult(rows)],
        )
        result, total = await ConversationArchiveStore(db).list_exchanges("c1")
        assert result == rows
        assert total == 2

    async def test_empty_result(self):
        db = FakeDB(execute_results=[FakeResult([0]), FakeResult([])])
        result, total = await ConversationArchiveStore(db).list_exchanges("c1")
        assert result == []
        assert total == 0


class TestMergeRuntimeExchange:
    async def test_none_when_not_running(self):
        assert await ConversationArchiveStore(FakeDB()).merge_runtime_exchange("c1") is None

    async def test_running_vo_fields(self):
        task = ChatTaskInfo(conversation_id="c1", question="进行中问题")
        task.answer_buffer = ["部分", "答案"]
        task.total_tokens = 7
        ChatRuntimeRegistry.register(task)
        vo = await ConversationArchiveStore(FakeDB()).merge_runtime_exchange("c1")
        assert vo is not None
        assert vo["question"] == "进行中问题"
        assert vo["answer"] == "部分答案"
        assert vo["tokens_used"] == 7
        assert vo["status"] == "running"
        assert vo["elapsed_ms"] >= 0

    async def test_running_vo_without_exchange_id_defaults_zero(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        ChatRuntimeRegistry.register(task)
        vo = await ConversationArchiveStore(FakeDB()).merge_runtime_exchange("c1")
        assert vo["id"] == 0
