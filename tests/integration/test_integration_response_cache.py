"""响应缓存集成测试（真实 Redis：命中/未命中/有历史跳过）"""

import pytest


@pytest.mark.asyncio
async def test_cache_roundtrip_real_redis(integration_env):
    from app.chat.response_cache import build_cache_key, lookup, store
    from app.infra.redis_lease import close_redis, get_redis, init_redis

    await init_redis()
    redis = get_redis()
    await redis.flushdb()
    try:
        async def _no_history(db, cid):
            return False

        import app.chat.response_cache as rc

        original = rc.has_history
        rc.has_history = _no_history

        class _FakeDb:
            pass

        # 未命中
        hit = await lookup(_FakeDb(), "c1", "什么是 RAG", "auto", [])
        assert hit is None

        # 写入
        events = [
            'data: {"type": "text", "content": "缓存答案"}',
            'data: {"type": "done", "conversationId": "c1", "exchangeId": 1}',
        ]
        await store(_FakeDb(), "c1", "什么是 RAG", "auto", [], events, "缓存答案")

        # 命中（跨会话：不同 conversation_id 同问题 → 命中）
        hit = await lookup(_FakeDb(), "c2", "什么是RAG", "auto", [])
        assert hit is not None
        assert hit.answer == "缓存答案"
        assert len(hit.events) == 2
        assert "缓存答案" in hit.events[0]

        # 键存在且 TTL 约 24h
        key = build_cache_key("什么是 RAG", "auto", [])
        ttl = await redis.ttl(key)
        assert 23 * 3600 < ttl <= 24 * 3600

        rc.has_history = original
    finally:
        await redis.flushdb()
        await close_redis()
