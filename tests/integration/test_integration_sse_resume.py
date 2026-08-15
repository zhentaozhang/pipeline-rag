"""SSE 断线续传（第二轮架构评审·可以优化 4）：缓冲写入 + resume 重放（真实 Redis）"""

import pytest


@pytest.mark.asyncio
async def test_sse_buffer_append_and_replay(integration_env):
    from app.api.chat_stream import _append_event, _contains_done, _replay_events
    from app.infra.redis_lease import close_redis, get_redis, init_redis

    await init_redis()
    redis = get_redis()
    await redis.flushdb()
    try:
        conv = "conv-resume-1"
        events = [
            'data: {"type": "thinking", "content": "思考中"}',
            'data: {"type": "text", "content": "第一部分"}',
            'data: {"type": "text", "content": "第二部分"}',
            'data: {"type": "done", "conversationId": "conv-resume-1"}',
        ]
        for raw in events:
            await _append_event(conv, raw)

        # 全量重放（resume=0 不重放，resume=1 起）
        replayed = await _replay_events(conv, 1)
        assert len(replayed) == 3
        assert "第二部分" in replayed[1]
        assert _contains_done(replayed) is True

        # resume 到 done 之后：重放 done 即可收尾
        replayed2 = await _replay_events(conv, 3)
        assert len(replayed2) == 1
        assert _contains_done(replayed2) is True

        # resume<=0 视为未续传 → 返回空（由正常流接管）
        replayed3 = await _replay_events(conv, 0)
        assert replayed3 == []

        # 原流仍在执行（缓冲无 done）→ 重放不含 done
        await redis.delete("pipeline_rag:sse:buf:conv-resume-2")
        for raw in events[:2]:
            await _append_event("conv-resume-2", raw)
        replayed4 = await _replay_events("conv-resume-2", 1)
        assert len(replayed4) == 1
        assert _contains_done(replayed4) is False
    finally:
        await redis.flushdb()
        await close_redis()
