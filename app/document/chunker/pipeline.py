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

        if ChunkStrategyType.RECURSIVE in self.strategies:
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

        if ChunkStrategyType.LLM in self.strategies:
            llm_chunks = await LLMChunker().chunk(text, doc_id, self.config)
            child_chunks.extend(llm_chunks)

        logger.info(
            "chunk pipeline done",
            doc_id=doc_id,
            parents=len(parent_chunks),
            children=len(child_chunks),
        )
        return parent_chunks + child_chunks
