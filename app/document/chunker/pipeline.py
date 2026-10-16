import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.llm import LLMChunker
from app.document.chunker.models import Chunk, ChunkStrategyType
from app.document.chunker.recursive import RecursiveChunker
from app.document.chunker.semantic import SemanticChunker
from app.document.chunker.structure import StructureChunker

logger = structlog.get_logger(__name__)


class ChunkPipeline:
    def __init__(
        self,
        strategies: list[ChunkStrategyType],
        config: ChunkConfig | None = None,
    ) -> None:
        self.strategies = strategies
        self.config = config or ChunkConfig()

    async def run(self, text: str, doc_id: str) -> list[Chunk]:
        parent_chunks: list[Chunk] = []
        child_chunks: list[Chunk] = []

        if ChunkStrategyType.STRUCTURE in self.strategies:
            parent_chunks = await StructureChunker().chunk(text, doc_id, self.config)

        if ChunkStrategyType.LLM in self.strategies:
            if not parent_chunks:
                child_chunks = await LLMChunker().chunk(text, doc_id, self.config)
                if not child_chunks and ChunkStrategyType.RECURSIVE in self.strategies:
                    child_chunks = await RecursiveChunker().chunk(text, doc_id, self.config)
            else:
                for p in parent_chunks:
                    p_children = await LLMChunker().chunk(p.content, doc_id, self.config)
                    for c in p_children:
                        c.parent_chunk_id = p.chunk_id
                        c.section_title = p.section_title
                        c.section_path = p.section_path
                        c.structure_node_id = p.structure_node_id
                        c.structure_node_type = p.structure_node_type
                        c.canonical_path = p.canonical_path
                    child_chunks.extend(p_children)
                if not child_chunks and ChunkStrategyType.RECURSIVE in self.strategies:
                    child_chunks = await RecursiveChunker().chunk_parents(
                        parent_chunks, self.config
                    )
        elif ChunkStrategyType.RECURSIVE in self.strategies:
            if not parent_chunks:
                child_chunks = await RecursiveChunker().chunk(text, doc_id, self.config)
            else:
                child_chunks = await RecursiveChunker().chunk_parents(parent_chunks, self.config)
        else:
            for p in parent_chunks:
                p.chunk_type = "child"
                child_chunks.append(p)
            parent_chunks = []

        if ChunkStrategyType.SEMANTIC in self.strategies and child_chunks:
            child_chunks = await SemanticChunker().chunk(child_chunks, self.config)

        for idx, c in enumerate(child_chunks):
            c.chunk_index = idx

        logger.info(
            "chunk pipeline done",
            doc_id=doc_id,
            parents=len(parent_chunks),
            children=len(child_chunks),
        )
        return parent_chunks + child_chunks
