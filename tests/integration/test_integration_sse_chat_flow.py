"""集成测试：SSE 流式对话核心链路（租约 → 状态机 → SSE 协议 → 持久化）。

检索/生成由 mock 提供（单元层已覆盖），本测试验证跨层编排：
真实 MySQL 会话落库 + 真实 Redis 租约 + SSE 事件序列。
"""

import json

import pytest


def _make_fake_registry(events: list[str]):
    """Fake ExecutorRegistry.dispatch：直接 yield SSE 事件"""

    class FakeRegistry:
        def __init__(self, db, task):
            self.task = task

        async def dispatch(self, plan):
            for ev in events:
                yield ev

    return FakeRegistry


async def _setup_infra():
    from app.db.session import close_db, init_db
    from app.infra.pg import close_pg, init_pg
    from app.infra.redis_lease import close_redis, init_redis

    await init_db()
    await init_pg()
    await init_redis()
    # 清理历史测试残留的租约锁（避免 lease conflict 误判）
    import redis.asyncio as aioredis

    from app.config import get_settings

    s = get_settings()
    rc = aioredis.from_url(s.redis.url, decode_responses=True)
    await rc.flushdb()
    await rc.aclose()
    return close_db, close_pg, close_redis


async def _teardown_infra(close_db, close_pg, close_redis):
    await close_redis()
    await close_pg()
    await close_db()


def _sse_events(stream: list[str]) -> list[dict]:
    events = []
    for chunk in stream:
        raw = chunk.removeprefix("data: ").strip()
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events


@pytest.mark.integration
async def test_sse_flow_persists_exchange(monkeypatch, mysql_tables):
    close_db, close_pg, close_redis = await _setup_infra()
    try:
        # 幂等：清理历史测试残留的会话数据
        from sqlalchemy import delete as sa_delete

        import app.db.session as _dbs
        from app.db.models.conversation import (
            ConversationExchange,
            ConversationMemory,
            ConversationSession,
        )

        assert _dbs._session_factory is not None
        async with _dbs._session_factory() as _db:
            await _db.execute(sa_delete(ConversationExchange))
            await _db.execute(sa_delete(ConversationMemory))
            await _db.execute(sa_delete(ConversationSession))
            await _db.commit()
        from app.chat.schema import ExecutionPlan
        from app.common.enums import ExecutionMode
        from app.common.sse import SSEEventType, sse_event

        # ── mock 编排层：prepare 返回固定 plan ──
        async def fake_prepare(**kwargs):
            return ExecutionPlan(
                question=kwargs.get("question", "q"),
                original_question=kwargs.get("question", "q"),
                rewritten_question=kwargs.get("question", "q"),
                mode=ExecutionMode.RETRIEVAL,
                current_date_text=kwargs.get("current_date_text", ""),
            )

        monkeypatch.setattr("app.orchestrator.orchestrator.prepare", fake_prepare)

        # ── mock trace 存储层：真实 Tracer 逻辑保留，仅不落 trace 表 ──
        class _NoopTraceStore:
            async def save_trace(self, *args, **kwargs):
                pass

            async def save_spans(self, *args, **kwargs):
                pass

            async def save_scores(self, *args, **kwargs):
                pass

        monkeypatch.setattr(
            "app.observability.storage.MySQLTraceStore", lambda *a, **k: _NoopTraceStore()
        )

        # ── mock 执行器：直接输出 text + done ──
        text_event = sse_event(SSEEventType.TEXT, "集成测试回答", conversation_id="conv-sse-1")
        done_event = sse_event(SSEEventType.DONE, conversation_id="conv-sse-1", exchange_id=1)
        FakeRegistry = _make_fake_registry([text_event, done_event])
        monkeypatch.setattr("app.executors.registry.ExecutorRegistry", FakeRegistry)

        # ── 真实服务链路 ──
        from types import SimpleNamespace

        from sqlalchemy import select

        from app.chat.service import BusinessChatService
        from app.db.models.conversation import ConversationExchange, ConversationSession

        request = SimpleNamespace(
            question="集成测试问题",
            conversation_id="conv-sse-1",
            chat_mode="auto",
            doc_ids=[],
            selected_document_id=None,
        )

        # 用独立 session（BusinessChatService 需要 db）
        import app.db.session as _dbs

        assert _dbs._session_factory is not None
        async with _dbs._session_factory() as db:
            service = BusinessChatService(db)
            stream = [chunk async for chunk in service.stream(request)]
            events = _sse_events(stream)
            types_seen = [e.get("type") for e in events]

            # SSE 协议断言：THINKING → TEXT → DONE
            assert SSEEventType.THINKING in types_seen
            assert SSEEventType.TEXT in types_seen
            assert types_seen[-1] == SSEEventType.DONE

            # 持久化断言：session + exchange 落库
            session = (
                await db.execute(
                    select(ConversationSession).where(
                        ConversationSession.conversation_id == "conv-sse-1"
                    )
                )
            ).scalar_one_or_none()
            assert session is not None

            exchange = (
                await db.execute(
                    select(ConversationExchange).where(
                        ConversationExchange.conversation_id == "conv-sse-1"
                    )
                )
            ).scalar_one_or_none()
            assert exchange is not None
            assert exchange.turn_status == 2  # 成功
            assert "集成测试回答" in (exchange.answer or "")
    finally:
        await _teardown_infra(close_db, close_pg, close_redis)
