"""响应缓存（第二轮架构评审·可以优化 3）：键/可缓存性/命中与回写逻辑"""

import pytest

from app.chat.response_cache import _normalize_question, build_cache_key, is_cacheable


def test_normalize_question():
    assert _normalize_question("  什么是 RAG ？  ") == "什么是rag？"
    assert _normalize_question("A  B  C") == "abc"


def test_cache_key_stable_and_scoped():
    k1 = build_cache_key("什么是 RAG", "auto", ["d1"])
    k2 = build_cache_key("  什么是RAG  ", "auto", ["d1"])  # 规范化后同键
    assert k1 == k2
    # 文档集不同 → 键不同
    k3 = build_cache_key("什么是 RAG", "auto", ["d2"])
    assert k1 != k3
    # 模式不同 → 键不同
    k4 = build_cache_key("什么是 RAG", "agent", ["d1"])
    assert k1 != k4
    # 跨会话复用：不含 conversation_id
    assert "conv" not in k1


def test_is_cacheable_rules():
    assert is_cacheable("auto", has_history=False) is True
    assert is_cacheable("retrieval", has_history=False) is True
    # 有历史上下文 → 不缓存（避免多轮污染）
    assert is_cacheable("auto", has_history=True) is False
    # 非确定性模式 → 不缓存
    assert is_cacheable("agent", has_history=False) is False
    assert is_cacheable("graph", has_history=False) is False


@pytest.mark.asyncio
async def test_lookup_and_store_roundtrip(monkeypatch):
    """真实 Redis 往返（键构建 + 存储 + 命中）——走集成测试更稳，此处用 fake"""
    from app.chat.response_cache import lookup, store

    calls = {"get": None, "set": None}

    class _FakeRedis:
        async def get(self, key):
            calls["get"] = key
            return None

        async def set(self, key, value, ex=None):
            calls["set"] = (key, value, ex)

    import app.chat.response_cache as rc

    monkeypatch.setattr(rc, "get_redis", lambda: _FakeRedis())
    async def _no_history(db, cid):
        return False

    monkeypatch.setattr(rc, "has_history", _no_history)

    class _FakeDb:
        pass

    hit = await lookup(_FakeDb(), "c1", "什么是 RAG", "auto", [])
    assert hit is None  # 无缓存 → miss
    assert calls["get"] is not None

    await store(
        _FakeDb(), "c1", "什么是 RAG", "auto", [],
        ['data: {"type": "text", "content": "答案"}', 'data: {"type": "done"}'],
        "答案",
    )
    assert calls["set"] is not None
    key, value, ex = calls["set"]
    assert ex == 24 * 3600
    assert "答案" in value


@pytest.mark.asyncio
async def test_lookup_skips_when_history_exists(monkeypatch):
    """有历史上下文 → 不查缓存（返回 None 且不访问 Redis）"""
    import app.chat.response_cache as rc

    called = {"get": False}

    class _FakeRedis:
        async def get(self, key):
            called["get"] = True
            return None

    monkeypatch.setattr(rc, "get_redis", lambda: _FakeRedis())
    async def _has_history(db, cid):
        return True

    monkeypatch.setattr(rc, "has_history", _has_history)

    class _FakeDb:
        pass

    hit = await rc.lookup(_FakeDb(), "c1", "问题", "auto", [])
    assert hit is None
    assert called["get"] is False  # 未访问 Redis
