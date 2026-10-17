import math

import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk

logger = structlog.get_logger(__name__)


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    return dot / (norm1 * norm2) if (norm1 > 0 and norm2 > 0) else 0.0


class SemanticChunker:
    """语义合并/切分器：优先使用 Embedding 向量余弦相似度合并相邻语义块，降级使用词法 Jaccard 重叠"""

    async def chunk(self, chunks: list[Chunk], config: ChunkConfig) -> list[Chunk]:
        if not chunks or len(chunks) == 1:
            return chunks

        from app.config import get_settings

        settings = get_settings()

        # 优先使用向量语义相似度（若可用）
        try:
            return await self._chunk_via_embeddings(chunks, config, settings)
        except Exception as e:
            logger.debug(
                "vector semantic chunking unavailable, falling back to lexical overlap",
                error=str(e),
            )
            return self._chunk_via_lexical(chunks, config, settings)

    async def _chunk_via_embeddings(
        self, chunks: list[Chunk], config: ChunkConfig, settings
    ) -> list[Chunk]:
        from app.infra.embedding import get_embedding_provider

        provider = get_embedding_provider()
        texts = [c.content for c in chunks]
        batch_size = getattr(settings.rag, "vectorize_batch_size", 32) or 32
        embs = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_embs = await provider.embed_batch(batch_texts)
            embs.extend(batch_embs)

        threshold = getattr(settings.chunk, "semantic_vector_threshold", 0.75) or 0.75

        merged_chunks: list[Chunk] = []
        current_chunk = chunks[0]
        current_emb = embs[0]

        for i in range(1, len(chunks)):
            next_chunk = chunks[i]
            next_emb = embs[i]

            same_parent = getattr(current_chunk, "parent_chunk_id", None) == getattr(
                next_chunk, "parent_chunk_id", None
            )
            sim = _cosine_similarity(current_emb, next_emb)
            merged_token_count = current_chunk.token_count + next_chunk.token_count
            if same_parent and sim >= threshold and merged_token_count <= config.max_chunk_size:
                w1 = max(1, current_chunk.token_count)
                w2 = max(1, next_chunk.token_count)
                total_w = w1 + w2
                current_emb = [
                    (c1 * w1 + c2 * w2) / total_w
                    for c1, c2 in zip(current_emb, next_emb, strict=False)
                ]
                current_chunk.content = current_chunk.content + "\n" + next_chunk.content
                current_chunk.token_count = merged_token_count
            else:
                merged_chunks.append(current_chunk)
                current_chunk = next_chunk
                current_emb = next_emb

        merged_chunks.append(current_chunk)
        for idx, mc in enumerate(merged_chunks):
            mc.chunk_index = idx

        logger.info("vector semantic chunker done", original=len(chunks), merged=len(merged_chunks))
        return merged_chunks

    def _chunk_via_lexical(self, chunks: list[Chunk], config: ChunkConfig, settings) -> list[Chunk]:
        import jieba

        texts = [c.content for c in chunks]

        def get_tokens(text: str) -> set[str]:
            return set(jieba.cut(text))

        def jaccard_sim(set_a: set[str], set_b: set[str]) -> float:
            if not set_a and not set_b:
                return 1.0
            intersection = set_a.intersection(set_b)
            union = set_a.union(set_b)
            return len(intersection) / len(union) if union else 0.0

        token_sets = [get_tokens(t) for t in texts]

        merged_chunks: list[Chunk] = []
        current_chunk = chunks[0]
        current_tokens = token_sets[0]

        similarity_threshold = settings.chunk.semantic_similarity_threshold

        for i in range(1, len(chunks)):
            next_chunk = chunks[i]
            next_tokens = token_sets[i]

            same_parent = getattr(current_chunk, "parent_chunk_id", None) == getattr(
                next_chunk, "parent_chunk_id", None
            )
            sim = jaccard_sim(current_tokens, next_tokens)

            merged_token_count = current_chunk.token_count + next_chunk.token_count
            if (
                same_parent
                and sim >= similarity_threshold
                and merged_token_count <= config.max_chunk_size
            ):
                current_chunk.content = current_chunk.content + "\n" + next_chunk.content
                current_chunk.token_count = merged_token_count
                current_tokens = current_tokens.union(next_tokens)
            else:
                merged_chunks.append(current_chunk)
                current_chunk = next_chunk
                current_tokens = next_tokens

        merged_chunks.append(current_chunk)

        for idx, mc in enumerate(merged_chunks):
            mc.chunk_index = idx

        logger.info(
            "lexical semantic chunker done", original=len(chunks), merged=len(merged_chunks)
        )
        return merged_chunks
