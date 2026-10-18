"""
向量检索通道（PGVector）

使用 asyncpg 直接查询 pipeline_rag_document_embedding 表，
基于 cosine similarity 过滤并排序。
"""

from typing import Any

import structlog

from app.chat.schema import Evidence, SubQuestion
from app.common.llm_client import get_embedding_client
from app.common.utils import safe_int
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


_EMBED_CACHE: dict[str, list[float]] = {}
_MAX_EMBED_CACHE_SIZE: int = 512


class VectorRetrievalChannel:
    """
    PGVector 语义检索通道。
    先用 OpenAI embedding 将查询向量化，再做 cosine similarity 查询。
    """

    def __init__(self) -> None:
        self._openai = get_embedding_client()

    async def _embed(self, text: str) -> list[float]:
        """调用 Embedding API 获取查询向量（带内存 LRU 缓存，避免重复计算）"""
        cache_key = text.strip()
        if cache_key in _EMBED_CACHE:
            vec = _EMBED_CACHE.pop(cache_key)
            _EMBED_CACHE[cache_key] = vec
            return vec

        resp = await self._openai.embeddings.create(
            model=settings.llm.embedding_model,
            input=text,
        )
        vec = resp.data[0].embedding
        if len(_EMBED_CACHE) >= _MAX_EMBED_CACHE_SIZE:
            # 淘汰最先插入的一项
            first_key = next(iter(_EMBED_CACHE))
            _EMBED_CACHE.pop(first_key, None)
        _EMBED_CACHE[cache_key] = vec
        return vec

    @staticmethod
    def _build_sql(sub_q: SubQuestion, embedding_str: str, limit: int) -> tuple[str, list]:
        sql = """
            SELECT id AS chunk_id, 
                   document_id, 
                   section_path, 
                   chunk_text AS content,
                   metadata_json->>'documentName' AS document_name,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM pipeline_rag_document_embedding
            WHERE 1=1
        """

        # args 混装 str / int / list，显式标注为 list[Any]
        args: list[Any] = [embedding_str]
        param_idx = 2

        if sub_q.tenant_id:
            sql += f" AND tenant_id = ${param_idx}"
            args.append(sub_q.tenant_id)
            param_idx += 1

        if sub_q.scope_code:
            sql += f" AND metadata_json->>'scope_code' = ${param_idx}"
            args.append(sub_q.scope_code)
            param_idx += 1

        if sub_q.doc_ids:
            doc_id_ints = [d for d in (safe_int(x) for x in sub_q.doc_ids) if d != 0]
            if doc_id_ints:
                sql += f" AND document_id = ANY(${param_idx}::bigint[])"
                args.append(doc_id_ints)
                param_idx += 1

        if sub_q.structure_node_id is not None:
            sql += f" AND structure_node_id = ${param_idx}"
            args.append(sub_q.structure_node_id)
            param_idx += 1

        if sub_q.section_path:
            sql += f" AND section_path LIKE ${param_idx}"
            args.append(sub_q.section_path + "%")
            param_idx += 1

        if sub_q.canonical_path:
            sql += f" AND canonical_path LIKE ${param_idx}"
            args.append(sub_q.canonical_path + "%")
            param_idx += 1

        if sub_q.item_index is not None:
            sql += f" AND item_index = ${param_idx}"
            args.append(sub_q.item_index)
            param_idx += 1

        if sub_q.document_name_hints:
            placeholders = ", ".join(
                f"${param_idx + i}" for i in range(len(sub_q.document_name_hints))
            )
            sql += f" AND metadata_json->>'documentName' ILIKE ANY(ARRAY[{placeholders}])"
            args.extend(f"%{h}%" for h in sub_q.document_name_hints)
            param_idx += len(sub_q.document_name_hints)

        if sub_q.business_category_hints:
            placeholders = ", ".join(
                f"${param_idx + i}" for i in range(len(sub_q.business_category_hints))
            )
            sql += f" AND metadata_json->>'businessCategory' = ANY(ARRAY[{placeholders}])"
            args.extend(sub_q.business_category_hints)
            param_idx += len(sub_q.business_category_hints)

        if sub_q.document_tag_hints:
            placeholders = ", ".join(
                f"${param_idx + i}" for i in range(len(sub_q.document_tag_hints))
            )
            sql += f" AND COALESCE(string_to_array(metadata_json->>'documentTags', ','), ARRAY[]::text[]) && ARRAY[{placeholders}]"
            args.extend(sub_q.document_tag_hints)
            param_idx += len(sub_q.document_tag_hints)

        sql += f" ORDER BY embedding <=> $1::vector ASC LIMIT ${param_idx}"
        args.append(limit)

        return sql, args

    async def retrieve(self, sub_q: SubQuestion) -> list[Evidence]:
        """
        向量相似度检索。
        """

        logger.debug("vector channel query", sub_q=sub_q.text[:50])

        # 1. 向量化查询
        try:
            query_embedding = await self._embed(sub_q.text)
        except Exception as e:
            logger.error("failed to embed query", error=str(e), exc_info=True)
            return []

        # 2. 序列化 embedding 为 pgvector 格式
        embedding_str = f"[{','.join(str(f) for f in query_embedding)}]"

        # 3. 构建 SQL
        top_k = settings.rag.vector_top_k
        max_k = getattr(settings.rag, "max_channel_top_k", 50) or 50
        limit = 10 if top_k <= 0 else min(top_k, max_k)
        sql, args = self._build_sql(sub_q, embedding_str, limit)

        from app.infra.pg import fetch as _pg_fetch

        evidences: list[Evidence] = []

        try:
            rows = await _pg_fetch(sql, *args)
        except Exception as e:
            logger.error("pgvector query failed", error=str(e), exc_info=True)
            return evidences

        for row in rows:
            evidences.append(
                Evidence(
                    chunk_id=str(row["chunk_id"]),
                    content=row["content"],
                    title=row["section_path"] or row.get("document_name", "") or "未知文档片段",
                    source_type="document",
                    score=float(row["similarity"]),
                    original_score=float(row["similarity"]),
                    channel="vector",
                    doc_id=str(row["document_id"]),
                )
            )

        return evidences
