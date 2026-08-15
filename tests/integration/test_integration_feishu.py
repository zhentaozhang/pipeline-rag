"""P3-4：飞书渠道集成测试（真实 MySQL 会话映射 + 全链路流式，mock 卡片发送/编排）"""

import pytest

from app.chat.schema import ExecutionPlan
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType, sse_event


def _install_mocks(monkeypatch):
    """mock 编排/检索/生成 + trace 存储 + 飞书卡片发送，返回调用记录"""
    calls = {"cards": [], "updates": [], "errors": []}

    async def fake_prepare(**kwargs):
        return ExecutionPlan(
            question=kwargs.get("question", "q"),
            original_question=kwargs.get("question", "q"),
            rewritten_question=kwargs.get("question", "q"),
            mode=ExecutionMode.RETRIEVAL,
            current_date_text="",
        )

    monkeypatch.setattr("app.orchestrator.orchestrator.prepare", fake_prepare)


    class FakeRegistry:
        def __init__(self, db, task):
            self.task = task

        async def dispatch(self, plan):
            yield sse_event(SSEEventType.THINKING, "正在检索知识库", conversation_id="c")
            yield sse_event(SSEEventType.TEXT, "这是飞书渠道的答案", conversation_id="c")
            yield sse_event(SSEEventType.DONE, conversation_id="c", exchange_id=99)

    monkeypatch.setattr("app.executors.registry.ExecutorRegistry", FakeRegistry)

    # trace 存储 no-op
    class _NoopTraceStore:
        async def save_trace(self, *a, **k):
            pass

        async def save_spans(self, *a, **k):
            pass

        async def save_scores(self, *a, **k):
            pass

    monkeypatch.setattr(
        "app.observability.storage.MySQLTraceStore", lambda *a, **k: _NoopTraceStore()
    )

    # 飞书卡片：记录调用
    def fake_send_card(chat_id, content):
        calls["cards"].append((chat_id, content))
        return "msg-1"

    def fake_update_card(message_id, content):
        calls["updates"].append((message_id, content))

    monkeypatch.setattr("app.chat.channels.feishu_client.send_card", fake_send_card)
    monkeypatch.setattr("app.chat.channels.feishu_client.update_card", fake_update_card)
    return calls


def _ensure_feishu_table():
    """集成环境表由 create_all 建：幂等补建新表"""
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import Base

    engine = create_engine(get_settings().mysql.sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.mark.asyncio
async def test_feishu_full_flow_with_conversation_binding(integration_env, monkeypatch):
    from sqlalchemy import select

    import app.db.session as _dbs
    from app.chat.channels.feishu_event_handler import _answer_question
    from app.db.models.conversation import ConversationSession, FeishuBinding
    from app.db.session import close_db, init_db
    from app.infra.redis_lease import close_redis, init_redis

    _ensure_feishu_table()
    await init_db()
    await init_redis()
    import redis.asyncio as aioredis

    from app.config import get_settings

    rc = aioredis.from_url(get_settings().redis.url, decode_responses=True)
    await rc.flushdb()
    await rc.aclose()
    assert _dbs._session_factory is not None

    # 清理残留
    async with _dbs._session_factory() as db:
        await db.execute(
            __import__("sqlalchemy").delete(FeishuBinding).where(FeishuBinding.chat_id == "oc_it_1")
        )
        await db.commit()

    calls = _install_mocks(monkeypatch)
    await _answer_question("oc_it_1", "ou_it_user", "飞书测试问题")

    # 1. 会话映射落库
    async with _dbs._session_factory() as db:
        binding = (
            await db.execute(
                select(FeishuBinding).where(
                    FeishuBinding.chat_id == "oc_it_1", FeishuBinding.open_id == "ou_it_user"
                )
            )
        ).scalar_one()
        assert binding.conversation_id
        # 2. 平台会话持久化（BusinessChatService 全链路真实执行）
        session = (
            await db.execute(
                select(ConversationSession).where(
                    ConversationSession.conversation_id == binding.conversation_id
                )
            )
        ).scalar_one_or_none()
        assert session is not None

    # 3. 卡片：初始 + 终态（含引用链接）
    assert len(calls["cards"]) == 1
    assert calls["cards"][0][0] == "oc_it_1"
    assert "思考" in calls["cards"][0][1]
    assert len(calls["updates"]) >= 1
    final = calls["updates"][-1][1]
    assert "飞书渠道的答案" in final
    assert "查看回答来源" in final  # 引用溯源 footer

    await close_redis()
    await close_db()


@pytest.mark.asyncio
async def test_conversation_binding_reuse(integration_env):
    """同一 (chat_id, open_id) 复用同一 conversation_id"""

    import app.db.session as _dbs
    from app.chat.channels.feishu_event_handler import resolve_conversation_id
    from app.db.models.conversation import FeishuBinding
    from app.db.session import close_db, init_db

    _ensure_feishu_table()
    await init_db()
    assert _dbs._session_factory is not None

    async with _dbs._session_factory() as db:
        await db.execute(
            __import__("sqlalchemy").delete(FeishuBinding).where(FeishuBinding.chat_id == "oc_it_2")
        )
        await db.commit()

        cid1, created1 = await resolve_conversation_id(db, "oc_it_2", "ou_it_2")
        cid2, created2 = await resolve_conversation_id(db, "oc_it_2", "ou_it_2")
        # 不同用户 → 不同会话（独立上下文）
        cid3, created3 = await resolve_conversation_id(db, "oc_it_2", "ou_other")

        assert cid1 == cid2
        assert created1 is True and created2 is False
        assert cid3 != cid1
        assert created3 is True

    await close_db()
