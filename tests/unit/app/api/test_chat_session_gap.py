import pytest

from app.api.chat_session_gap import SessionIdRequest, rebuild_summary


@pytest.mark.asyncio
async def test_rebuild_summary_returns_actual_summary(monkeypatch):
    class FakeMemoryService:
        def __init__(self, db):
            self.db = db

        async def rebuild_summary(self, conversation_id: str):
            pass

        async def get_summary(self, conversation_id: str) -> str:
            return "重新生成的完整摘要"

    monkeypatch.setattr(
        "app.chat.memory_service.PersistentConversationMemoryService",
        FakeMemoryService,
    )

    req = SessionIdRequest(conversation_id="conv-rebuild-1")
    resp = await rebuild_summary(req, db=None)
    assert resp["code"] == 0
    assert resp["data"]["conversationId"] == "conv-rebuild-1"
    assert resp["data"]["summary"] == "重新生成的完整摘要"
