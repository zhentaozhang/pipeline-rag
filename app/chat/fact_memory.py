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
        facts.append(UserFact(content=content, category=_norm_category(str(item.get("category", "fact")))))
    return facts


class FactMemoryStore:
    """事实记忆存取（pgvector + embedding API）"""

    def __init__(self) -> None:
        from app.infra.embedding import get_embedding_provider

        self._embedder = get_embedding_provider()

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.embed_batch(texts)

    async def retrieve(
        self, conversation_id: str, query_embedding: list[float], top_k: int
    ) -> list[str]:
        """检索与查询向量最相关的已记忆事实（余弦距离升序）"""
        from app.infra.pg import fetch

        embedding_str = f"[{','.join(str(f) for f in query_embedding)}]"
        rows = await fetch(
            """
            SELECT content FROM public.user_fact_memory
            WHERE conversation_id = $1
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            """,
            conversation_id,
            embedding_str,
            top_k,
        )
        return [str(r["content"]) for r in rows]

    async def insert_many(
        self,
        conversation_id: str,
        facts: list[UserFact],
        source_exchange_id: int | None,
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
                        (id, conversation_id, content, category, embedding, source_exchange_id)
                    VALUES ($1, $2, $3, $4, $5::vector, $6)
                    """,
                    next_id(),
                    conversation_id,
                    fact.content,
                    fact.category,
                    embedding_str,
                    source_exchange_id,
                )
                inserted += 1
            except Exception as e:
                logger.warning("fact memory insert failed", error=str(e), exc_info=True)
        return inserted
