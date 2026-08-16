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
