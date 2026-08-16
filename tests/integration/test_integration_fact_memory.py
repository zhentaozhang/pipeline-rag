"""P3 · 用户事实记忆集成测试（真实 PG：插入 + 相似度去重 + 向量检索）"""

import pytest


@pytest.mark.asyncio
async def test_fact_memory_insert_and_retrieve(integration_env):
    from app.chat.fact_memory import FactMemoryStore, UserFact
    from app.infra.pg import close_pg, execute, fetch, init_pg

    await init_pg()
    try:
        # 幂等补建表（init_pg 幂等跳过时新表可能不存在）
        await execute(
            """
            CREATE TABLE IF NOT EXISTS public.user_fact_memory (
                id BIGINT NOT NULL,
                conversation_id VARCHAR(64) NOT NULL,
                content TEXT NOT NULL,
                category VARCHAR(32) NOT NULL DEFAULT 'fact',
                embedding VECTOR NOT NULL,
                source_exchange_id BIGINT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                edit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id)
            )
            """
        )
        await execute(
            "CREATE INDEX IF NOT EXISTS idx_user_fact_conv ON public.user_fact_memory (conversation_id)"
        )
        store = FactMemoryStore()
        conv = "conv-fact-it"

        # 清理
        await execute("DELETE FROM public.user_fact_memory WHERE conversation_id = $1", conv)

        # mock embedding provider（固定向量，避免真实 API）
        class _FakeEmbedder:
            async def embed_batch(self, texts):
                # 内容含 "后端" 与 "后端工程师" 相近：用固定维度向量近似
                vecs = []
                for t in texts:
                    if "后端" in t:
                        vecs.append([1.0, 0.0, 0.0])
                    elif "偏好简洁" in t or "喜欢" in t:
                        vecs.append([0.0, 1.0, 0.0])
                    else:
                        vecs.append([0.0, 0.0, 1.0])
                return vecs

        store._embedder = _FakeEmbedder()

        # 插入两条不同事实
        n1 = await store.insert_many(
            conv, [UserFact("用户是后端工程师", "identity")], source_exchange_id=1
        )
        n2 = await store.insert_many(
            conv, [UserFact("用户偏好简洁回答", "preference")], source_exchange_id=2
        )
        assert n1 == 1 and n2 == 1

        # 去重：插入近似事实（同向量）→ 跳过
        n3 = await store.insert_many(
            conv, [UserFact("用户是后端工程师（重复）", "fact")], source_exchange_id=3
        )
        assert n3 == 0

        # 检索：查"后端"相关 → 命中身份事实
        facts = await store.retrieve(conv, [1.0, 0.0, 0.0], top_k=3)
        assert any("后端" in f for f in facts)
        assert "偏好简洁" not in facts[0]  # 按距离排序，后端相关在最前

        count = await fetch(
            "SELECT COUNT(*) AS c FROM public.user_fact_memory WHERE conversation_id = $1", conv
        )
        assert int(count[0]["c"]) == 2

        # 清理
        await execute("DELETE FROM public.user_fact_memory WHERE conversation_id = $1", conv)
    finally:
        await close_pg()


@pytest.mark.asyncio
async def test_fact_memory_cleanup_strategies(integration_env):
    """清理策略：按会话删除 / 容量淘汰（真实 PG）"""
    from app.chat.fact_memory import FactMemoryStore, UserFact
    from app.infra.pg import close_pg, execute, fetch, init_pg

    await init_pg()
    try:
        await execute(
            """
            CREATE TABLE IF NOT EXISTS public.user_fact_memory (
                id BIGINT NOT NULL,
                conversation_id VARCHAR(64) NOT NULL,
                content TEXT NOT NULL,
                category VARCHAR(32) NOT NULL DEFAULT 'fact',
                embedding VECTOR NOT NULL,
                source_exchange_id BIGINT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                edit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id)
            )
            """
        )
        store = FactMemoryStore()

        _VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.5, 0.5, 0.0]]

        class _FakeEmbedder:
            def __init__(self):
                self._i = 0

            async def embed_batch(self, texts):
                out = []
                for _ in texts:
                    out.append(_VECTORS[self._i % len(_VECTORS)])
                    self._i += 1
                return out

        store._embedder = _FakeEmbedder()

        conv = "conv-fact-clean"
        await execute("DELETE FROM public.user_fact_memory WHERE conversation_id = $1", conv)

        # 插入 3 条（内容不同 → 向量不同）
        await store.insert_many(
            conv,
            [UserFact(f"事实{i}", "fact") for i in range(3)],
            source_exchange_id=1,
        )
        count = await fetch(
            "SELECT COUNT(*) AS c FROM public.user_fact_memory WHERE conversation_id = $1", conv
        )
        assert int(count[0]["c"]) == 3

        # 容量淘汰：max=2 → 淘汰 1 条（最旧）
        removed = await store.enforce_capacity(conv, 2)
        assert removed == 1
        count = await fetch(
            "SELECT COUNT(*) AS c FROM public.user_fact_memory WHERE conversation_id = $1", conv
        )
        assert int(count[0]["c"]) == 2

        # 按会话删除
        deleted = await store.delete_by_conversation(conv)
        assert deleted == 2
        count = await fetch(
            "SELECT COUNT(*) AS c FROM public.user_fact_memory WHERE conversation_id = $1", conv
        )
        assert int(count[0]["c"]) == 0

        # 清理
        await execute("DELETE FROM public.user_fact_memory WHERE conversation_id = $1", conv)
    finally:
        await close_pg()
