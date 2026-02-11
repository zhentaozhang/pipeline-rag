import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk

logger = structlog.get_logger(__name__)


class SemanticChunker:
    async def chunk(self, chunks: list[Chunk], config: ChunkConfig) -> list[Chunk]:
        if not chunks or len(chunks) == 1:
            return chunks

        import jieba

        from app.config import get_settings

        settings = get_settings()
        logger.info("starting semantic chunker (jaccard)", count=len(chunks))

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

            sim = jaccard_sim(current_tokens, next_tokens)

            merged_token_count = current_chunk.token_count + next_chunk.token_count
            if sim >= similarity_threshold and merged_token_count <= config.max_chunk_size:
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

        logger.info("semantic chunker done", original=len(chunks), merged=len(merged_chunks))
        return merged_chunks
