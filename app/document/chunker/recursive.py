import asyncio

import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk
from app.document.chunker.sentence_splitter import split_text
from app.document.chunker.utils import count_tokens
from app.infra.id_generator import next_id_str

logger = structlog.get_logger(__name__)


class RecursiveChunker:
    async def chunk(self, text: str, doc_id: str, config: ChunkConfig) -> list[Chunk]:
        loop = asyncio.get_event_loop()

        def _split() -> list[str]:
            return split_text(text, config.chunk_size)

        try:
            text_chunks = await loop.run_in_executor(None, _split)
        except Exception as e:
            logger.error("recursive chunker failed", error=str(e), exc_info=True)
            return []

        results = []
        for i, txt in enumerate(text_chunks):
            txt = txt.strip()
            if len(txt) < config.min_chunk_size:
                continue

            results.append(
                Chunk(
                    chunk_id=next_id_str(),
                    doc_id=doc_id,
                    content=txt,
                    chunk_index=i,
                    token_count=count_tokens(txt),
                )
            )

        self._apply_overlap(results, config.chunk_overlap)
        logger.debug("recursive chunker", count=len(results))
        return results

    async def chunk_parents(self, parent_chunks: list[Chunk], config: ChunkConfig) -> list[Chunk]:
        loop = asyncio.get_event_loop()
        results = []

        for p_chunk in parent_chunks:
            if p_chunk.token_count <= config.chunk_size:
                results.append(
                    Chunk(
                        chunk_id=next_id_str(),
                        doc_id=p_chunk.doc_id,
                        content=p_chunk.content,
                        chunk_index=p_chunk.chunk_index,
                        chunk_type="child",
                        parent_chunk_id=p_chunk.chunk_id,
                        section_title=p_chunk.section_title,
                        token_count=p_chunk.token_count,
                        canonical_path=p_chunk.canonical_path,
                        section_path=p_chunk.section_path,
                        structure_node_id=p_chunk.structure_node_id,
                        structure_node_type=p_chunk.structure_node_type,
                        item_index=p_chunk.item_index,
                    )
                )
            else:
                try:
                    text_chunks = await loop.run_in_executor(None, split_text, p_chunk.content, config.chunk_size)
                except Exception as e:
                    logger.error("recursive chunker failed on parent", error=str(e), exc_info=True)
                    continue

                for i, txt in enumerate(text_chunks):
                    txt = txt.strip()
                    if len(txt) < config.min_chunk_size:
                        continue

                    results.append(
                        Chunk(
                            chunk_id=next_id_str(),
                            doc_id=p_chunk.doc_id,
                            content=txt,
                            chunk_index=i,
                            chunk_type="child",
                            parent_chunk_id=p_chunk.chunk_id,
                            section_title=p_chunk.section_title,
                            token_count=count_tokens(txt),
                            canonical_path=p_chunk.canonical_path,
                            section_path=p_chunk.section_path,
                            structure_node_id=p_chunk.structure_node_id,
                            structure_node_type=p_chunk.structure_node_type,
                            item_index=p_chunk.item_index,
                        )
                    )

        self._apply_overlap(results, config.chunk_overlap)
        return results

    def _apply_overlap(self, chunks: list[Chunk], overlap_tokens: int) -> None:
        if overlap_tokens <= 0 or len(chunks) < 2:
            return

        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            overlap_chars = overlap_tokens * 2
            for i in range(1, len(chunks)):
                prev_content = chunks[i - 1].content
                if len(prev_content) > overlap_chars:
                    suffix = prev_content[-overlap_chars:]
                else:
                    suffix = prev_content
                curr_content = chunks[i].content
                if not curr_content.startswith(suffix):
                    chunks[i].content = suffix + "\n" + curr_content
                    chunks[i].token_count = count_tokens(chunks[i].content)
            return

        for i in range(1, len(chunks)):
            prev_content = chunks[i - 1].content
            curr_content = chunks[i].content
            tokens = enc.encode(prev_content)
            if len(tokens) > overlap_tokens:
                suffix_tokens = tokens[-overlap_tokens:]
                suffix = enc.decode(suffix_tokens)
            else:
                suffix = prev_content
            if not curr_content.startswith(suffix):
                chunks[i].content = suffix + "\n" + curr_content
                chunks[i].token_count = count_tokens(chunks[i].content)
