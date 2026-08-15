"""
向量化服务
将文档 Chunk 转为 Embedding 向量，写入 PGVector
"""

from datetime import UTC

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils import safe_int
from app.config import get_settings
from app.document.chunker import Chunk
from app.infra.embedding import EmbeddingProvider, get_embedding_provider

logger = structlog.get_logger(__name__)
settings = get_settings()


class VectorizerService:
    """
    批量向量化 Chunk，写入 PGVector。
    使用可配置的 EmbeddingProvider。
    """

    def __init__(self, provider: EmbeddingProvider | None = None) -> None:
        self._provider = provider or get_embedding_provider()
        self._batch_size = settings.rag.vectorize_batch_size

    async def vectorize(
        self, chunks: list[Chunk], task_id: str = "0", document_name: str = ""
    ) -> int:
        """
        批量向量化并写入 PGVector。
        - 所有的 Chunk（Parent + Child）全部存入 document_chunk（用于被 RAG 时通过 parent_chunk_id 反查大段文本）
        - 仅 Child Chunk 提取 Embedding 并存入 pipeline_rag_document_embedding

        Returns:
            成功写入的 embedding 数量
        """
        logger.info(
            "vectorizing chunks", count=len(chunks), task_id=task_id, document_name=document_name
        )

        child_chunks = [c for c in chunks if c.chunk_type == "child"]
        logger.info(
            "filtered child chunks for embedding", total=len(chunks), child_count=len(child_chunks)
        )

        # 先获取 embeddings，仅针对 child_chunks
        # 注：批次失败时直接抛出，由 Celery 任务层标记失败并重试（max_retries=3），
        # 不写入全零向量——零向量会污染向量库并被检索命中（cosine 相似度对零向量无定义）。
        child_embeddings = []
        for i in range(0, len(child_chunks), self._batch_size):
            batch = child_chunks[i : i + self._batch_size]
            texts = [c.content for c in batch]
            embs = await self._embed_batch(texts)
            child_embeddings.extend(embs)
            logger.info("batch vectorized", batch=i // self._batch_size + 1, count=len(batch))

        # 落盘：全量存 document_chunk，部分存 embedding
        await self._write_to_pgvector(
            chunks,
            child_chunks,
            child_embeddings,
            task_id,
            getattr(chunks[0], "tenant_id", "default") if chunks else "default",
            document_name,
        )

        return len(child_chunks)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量调用嵌入提供者（支持 provider 切换）"""
        return await self._provider.embed_batch(texts)

    async def _write_to_pgvector(
        self,
        all_chunks: list[Chunk],
        child_chunks: list[Chunk],
        embeddings: list[list[float]],
        task_id: str = "0",
        tenant_id: str = "default",
        document_name: str = "",
    ) -> None:
        """写入 PGVector 表，使用 UPSERT 语义（ON CONFLICT DO UPDATE）"""
        import json
        from datetime import datetime

        from app.infra.pg import transaction as _pg_transaction

        chunk_sql = """
            chunk_id, tenant_id, doc_id, parent_chunk_id, chunk_index, content, 
            chunk_type, token_count, section_title
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (chunk_id) DO UPDATE SET
            content = EXCLUDED.content,
            token_count = EXCLUDED.token_count
        """

        embed_sql = """
        INSERT INTO pipeline_rag_document_embedding (
            id, tenant_id, document_id, task_id, plan_id, parent_block_id, chunk_no,
            source_type, section_path, structure_node_id, structure_node_type,
            canonical_path, item_index, chunk_text, char_count, token_count,
            embedding_model, metadata_json, embedding, create_time, edit_time, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18::jsonb, $19::vector, NOW(), NOW(), $20)
        ON CONFLICT (document_id, chunk_no) DO UPDATE SET
            id = EXCLUDED.id,
            task_id = EXCLUDED.task_id,
            plan_id = EXCLUDED.plan_id,
            parent_block_id = EXCLUDED.parent_block_id,
            source_type = EXCLUDED.source_type,
            section_path = EXCLUDED.section_path,
            structure_node_id = EXCLUDED.structure_node_id,
            structure_node_type = EXCLUDED.structure_node_type,
            canonical_path = EXCLUDED.canonical_path,
            item_index = EXCLUDED.item_index,
            chunk_text = EXCLUDED.chunk_text,
            char_count = EXCLUDED.char_count,
            token_count = EXCLUDED.token_count,
            embedding_model = EXCLUDED.embedding_model,
            metadata_json = EXCLUDED.metadata_json,
            embedding = EXCLUDED.embedding,
            edit_time = NOW(),
            status = EXCLUDED.status
        """

        datetime.now(UTC)
        embedding_model_name = settings.llm.embedding_model

        # Convert task_id to BIGINT for the embedding table
        # Use stable hash (Python builtin hash() is randomized per process)
        def _to_bigint(val: str | None) -> int:
            if val is None:
                return 0
            s = str(val)
            result = safe_int(s, default=None)
            if result is not None:
                return result
            import hashlib

            digest = hashlib.md5(s.encode("utf-8")).digest()
            return int.from_bytes(digest[:8], "big") % (10**15)

        task_id_bigint = _to_bigint(task_id) if task_id != "0" else 0

        async with _pg_transaction() as conn:
            # 0. 清理该文档的旧 chunk（避免 pipeline 重跑后累积重复）
            doc_id_to_clean = all_chunks[0].doc_id if all_chunks else None
            if doc_id_to_clean:
                await conn.execute("DELETE FROM document_chunk WHERE doc_id = $1", doc_id_to_clean)

            # 1. 保存所有块（含 Parent）的元数据文本 (批量)
            chunk_values = [
                (
                    chunk.chunk_id,
                    tenant_id,
                    chunk.doc_id,
                    chunk.parent_chunk_id,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.chunk_type,
                    chunk.token_count,
                    chunk.section_title,
                )
                for chunk in all_chunks
            ]
            if chunk_values:
                await conn.executemany(chunk_sql, chunk_values)

            # 2. 仅保存 Child 块的向量 (批量)，包含所有列
            embed_values = []
            for chunk, emb in zip(child_chunks, embeddings, strict=False):
                document_id = chunk.document_id or 0

                emb_id = _to_bigint(chunk.chunk_id)
                parent_id = _to_bigint(chunk.parent_chunk_id)

                metadata_json = json.dumps(
                    {
                        "documentId": document_id,
                        "documentName": document_name,
                        "taskId": task_id_bigint,
                        "planId": getattr(chunk, "plan_id", None),
                        "parentBlockId": parent_id,
                        "chunkNo": chunk.chunk_index,
                        "sourceType": getattr(chunk, "source_type", 0),
                        "sectionPath": chunk.section_path,
                        "structureNodeId": chunk.structure_node_id,
                        "structureNodeType": chunk.structure_node_type,
                        "canonicalPath": chunk.canonical_path,
                        "itemIndex": chunk.item_index if chunk.item_index else 0,
                        "charCount": len(chunk.content),
                        "tokenCount": chunk.token_count or 0,
                        "embeddingModel": embedding_model_name,
                    },
                    ensure_ascii=False,
                )

                # item_index 默认用 0，若有结构树字段也一并传
                item_index = getattr(chunk, "item_index", 0) or 0

                embed_values.append(
                    (
                        emb_id,
                        tenant_id,
                        document_id,
                        task_id_bigint,
                        0,
                        parent_id,
                        chunk.chunk_index,
                        0,
                        chunk.section_path or "",
                        safe_int(chunk.structure_node_id),
                        chunk.structure_node_type if chunk.structure_node_type else 0,
                        chunk.canonical_path or "",
                        item_index,
                        chunk.content,
                        chunk.token_count or 0,
                        chunk.token_count or 0,
                        embedding_model_name,
                        metadata_json,
                        json.dumps(emb),
                        1,
                    )
                )

            if embed_values:
                await conn.executemany(embed_sql, embed_values)

    async def delete_doc(self, db: AsyncSession, doc_id: str) -> None:
        """从 PGVector 中删除指定文档的所有块。"""
        from sqlalchemy import select

        from app.db.models.document import Document

        doc = (
            await db.execute(select(Document).where(Document.doc_id == doc_id))
        ).scalar_one_or_none()
        if not doc:
            return

        from app.infra.pg import transaction as _pg_transaction

        async with _pg_transaction() as conn:
            await conn.execute(
                "DELETE FROM pipeline_rag_document_embedding WHERE document_id = $1", doc.id
            )
            await conn.execute("DELETE FROM document_chunk WHERE doc_id = $1", doc_id)
            logger.info("pgvector doc deleted", doc_id=doc_id, document_id=doc.id)
