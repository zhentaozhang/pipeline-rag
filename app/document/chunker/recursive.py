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
        try:
            text_chunks = await asyncio.to_thread(split_text, text, config.chunk_size)
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
        for idx, c in enumerate(results):
            c.chunk_index = idx
        logger.debug("recursive chunker", count=len(results))
        return results

    async def chunk_parents(self, parent_chunks: list[Chunk], config: ChunkConfig) -> list[Chunk]:
        results: list[Chunk] = []

        for p_chunk in parent_chunks:
            if p_chunk.token_count <= config.chunk_size:
                results.append(
                    Chunk(
                        chunk_id=next_id_str(),
                        doc_id=p_chunk.doc_id,
                        content=p_chunk.content,
                        chunk_index=len(results),
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
                    text_chunks = await asyncio.to_thread(
                        split_text, p_chunk.content, config.chunk_size
                    )
                except Exception as e:
                    logger.error("recursive chunker failed on parent", error=str(e), exc_info=True)
                    continue

                for txt in text_chunks:
                    txt = txt.strip()
                    if len(txt) < config.min_chunk_size:
                        continue

                    results.append(
                        Chunk(
                            chunk_id=next_id_str(),
                            doc_id=p_chunk.doc_id,
                            content=txt,
                            chunk_index=len(results),
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
        # 确保跨父块生成的全量子块的 chunk_index 严格全局唯一递增，杜绝 PGVector 写入冲突丢失
        for idx, c in enumerate(results):
            c.chunk_index = idx
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
                # 严禁跨越父块边界添加 overlap
                if (
                    chunks[i].parent_chunk_id
                    and chunks[i - 1].parent_chunk_id
                    and chunks[i].parent_chunk_id != chunks[i - 1].parent_chunk_id
                ):
                    continue

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
            # 严禁跨越父块边界添加 overlap
            if (
                chunks[i].parent_chunk_id
                and chunks[i - 1].parent_chunk_id
                and chunks[i].parent_chunk_id != chunks[i - 1].parent_chunk_id
            ):
                continue

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
