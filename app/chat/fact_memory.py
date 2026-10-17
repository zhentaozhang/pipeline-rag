"""用户事实记忆存储（调研 P3 · Mem0 式）

从对话中抽取"值得长期记住"的用户事实/偏好，向量化存入 pgvector；
新对话开始时检索相关记忆注入 system prompt，实现跨轮个性化。

安全边界：
- 默认关闭（RAG_USER_MEMORY_ENABLED=false，隐私合规）
- 按 conversation_id 维度（同现有记忆体系）；如需全局用户画像可扩展 user_key
- 相似度去重：与已有事实相似度 > update_threshold 时不重复插入
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog

from app.config import get_settings
from app.infra.id_generator import next_id

logger = structlog.get_logger(__name__)
settings = get_settings()

_CATEGORIES = {"preference", "fact", "identity", "goal"}


@dataclass
class UserFact:
    content: str
    category: str = "fact"


def _norm_category(category: str) -> str:
    c = (category or "fact").strip().lower()
    return c if c in _CATEGORIES else "fact"


def parse_extraction_response(raw: str) -> list[UserFact]:
    """解析抽取 LLM 输出（容忍 code fence / 前后噪声）"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        payload = json.loads(text)
    except ValueError:
        # 尝试截取首个 [ ... ] 数组
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            payload = json.loads(text[start : end + 1])
        except ValueError:
            return []
    if not isinstance(payload, list):
        return []
    facts: list[UserFact] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content or len(content) < 4:
            continue
        facts.append(
            UserFact(content=content, category=_norm_category(str(item.get("category", "fact"))))
        )
    return facts


class FactMemoryStore:
    """事实记忆存取（pgvector + embedding API）"""

    def __init__(self) -> None:
        from app.infra.embedding import get_embedding_provider

        self._embedder = get_embedding_provider()

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.embed_batch(texts)

    async def retrieve(
        self,
        conversation_id: str,
        query_embedding: list[float],
        top_k: int,
        user_key: str | None = None,
        distance_threshold: float | None = None,
    ) -> list[str]:
        """检索相关已记忆事实（余弦距离升序，保留各类别最新事实）。

        user_key 提供时检索「用户级 + 会话级」记忆并集（跨会话画像）；
        否则仅检索会话级（向后兼容）。
        """
        from app.infra.pg import fetch

        threshold = (
            distance_threshold
            if distance_threshold is not None
            else getattr(settings.fact_memory, "retrieval_distance_threshold", 0.70)
        )
        embedding_str = f"[{','.join(str(f) for f in query_embedding)}]"
        limit = max(top_k * 10, 50)
        if user_key:
            rows = await fetch(
                """
                SELECT content, category, edit_time, (embedding <=> $3::vector) AS dist
                FROM public.user_fact_memory
                WHERE (user_key = $1 OR conversation_id = $2)
                  AND (embedding <=> $3::vector) <= $5
                ORDER BY embedding <=> $3::vector
                LIMIT $4
                """,
                user_key,
                conversation_id,
                embedding_str,
                limit,
                threshold,
            )
        else:
            rows = await fetch(
                """
                SELECT content, category, edit_time, (embedding <=> $2::vector) AS dist
                FROM public.user_fact_memory
                WHERE conversation_id = $1
                  AND (embedding <=> $2::vector) <= $4
                ORDER BY embedding <=> $2::vector
                LIMIT $3
                """,
                conversation_id,
                embedding_str,
                limit,
                threshold,
            )
        # 按 category 分组：同类事实只保留 edit_time 最新，若相同则取距离最小
        category_best: dict[str, dict] = {}
        for r in rows:
            cat = r.get("category") or "_"
            if cat not in category_best:
                category_best[cat] = r
            else:
                existing_time = category_best[cat].get("edit_time")
                current_time = r.get("edit_time")
                if (current_time and (not existing_time or current_time > existing_time)) or (
                    current_time == existing_time
                    and r.get("dist", 1.0) < category_best[cat].get("dist", 1.0)
                ):
                    category_best[cat] = r

        # 按原本相关性（dist）升序排序输出，不超过 top_k
        selected_rows = sorted(category_best.values(), key=lambda r: r.get("dist", 0.0))
        return [str(r["content"]) for r in selected_rows[:top_k]]

    async def delete_by_conversation(
        self, conversation_id: str, user_key: str | None = None
    ) -> int:
        """删除会话事实记忆。仅在显式传入有效 user_key 时才附带清除该用户跨会话记忆。"""
        if not conversation_id or not conversation_id.strip():
            return 0
        from app.infra.pg import execute

        cid = conversation_id.strip()
        uk = user_key.strip() if user_key and user_key.strip() else None
        if uk:
            result = await execute(
                "DELETE FROM public.user_fact_memory WHERE conversation_id = $1 OR user_key = $2",
                cid,
                uk,
            )
        else:
            result = await execute(
                "DELETE FROM public.user_fact_memory WHERE conversation_id = $1",
                cid,
            )
        return int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0

    async def delete_by_user(self, user_key: str) -> int:
        """按用户标识彻底清除该用户的所有事实记忆（用户注销/隐私擦除）。"""
        if not user_key or not user_key.strip():
            return 0
        from app.infra.pg import execute

        result = await execute(
            "DELETE FROM public.user_fact_memory WHERE user_key = $1",
            user_key.strip(),
        )
        return int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0

    async def enforce_capacity(self, conversation_id: str, max_facts: int) -> int:
        """容量上限：超出 max_facts 时按 edit_time 最旧淘汰，返回淘汰数"""
        if max_facts <= 0:
            return 0
        from app.infra.pg import execute

        try:
            result = await execute(
                """
                DELETE FROM public.user_fact_memory
                WHERE id IN (
                    SELECT id FROM public.user_fact_memory
                    WHERE conversation_id = $1
                    ORDER BY edit_time ASC
                    OFFSET $2
                )
                """,
                conversation_id,
                max_facts,
            )
            return int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
        except Exception as e:
            logger.warning("fact memory capacity prune failed", error=str(e), exc_info=True)
            return 0

    async def prune_expired(self, retention_days: int) -> int:
        """全局保留期清理：edit_time 早于 retention_days 的事实删除（0 或负数表示不限）"""
        if retention_days <= 0:
            return 0
        from app.infra.pg import execute

        try:
            result = await execute(
                """
                DELETE FROM public.user_fact_memory
                WHERE edit_time < NOW() - ($1 * INTERVAL '1 day')
                """,
                retention_days,
            )
            return int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
        except Exception as e:
            logger.warning("fact memory retention prune failed", error=str(e), exc_info=True)
            return 0

    async def insert_many(
        self,
        conversation_id: str,
        facts: list[UserFact],
        source_exchange_id: int | None,
        user_key: str | None = None,
    ) -> int:
        """插入新事实（去重：与已有事实相似度 > threshold 跳过）。返回插入条数"""
        if not facts:
            return 0
        from app.infra.pg import execute, fetchval

        settings = get_settings().fact_memory
        threshold = settings.update_threshold
        inserted = 0
        for fact in facts:
            emb = (await self._embed([fact.content]))[0]
            embedding_str = f"[{','.join(str(f) for f in emb)}]"
            try:
                if user_key:
                    similar = await fetchval(
                        """
                        SELECT COUNT(*) FROM public.user_fact_memory
                        WHERE (user_key = $1 OR conversation_id = $2)
                          AND embedding <=> $3::vector < $4
                        """,
                        user_key,
                        conversation_id,
                        embedding_str,
                        1.0 - threshold,
                    )
                else:
                    similar = await fetchval(
                        """
                        SELECT COUNT(*) FROM public.user_fact_memory
                        WHERE conversation_id = $1
                          AND embedding <=> $2::vector < $3
                        """,
                        conversation_id,
                        embedding_str,
                        1.0 - threshold,
                    )
                if similar is not None and int(str(similar)) > 0:
                    continue  # 已有近似事实，去重
                await execute(
                    """
                    INSERT INTO public.user_fact_memory
                        (id, conversation_id, user_key, content, category, embedding, source_exchange_id)
                    VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
                    """,
                    next_id(),
                    conversation_id,
                    user_key,
                    fact.content,
                    fact.category,
                    embedding_str,
                    source_exchange_id,
                )
                inserted += 1
            except Exception as e:
                logger.warning("fact memory insert failed", error=str(e), exc_info=True)
        if inserted > 0:
            await self.enforce_capacity(conversation_id, settings.max_facts)
        return inserted
