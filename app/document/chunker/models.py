from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChunkStrategyType(StrEnum):
    STRUCTURE = "structure"
    RECURSIVE = "recursive"
    SEMANTIC = "semantic"
    LLM = "llm"


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    content: str
    chunk_index: int
    chunk_type: str = "child"
    parent_chunk_id: str | None = None
    section_title: str | None = None
    token_count: int = 0
    canonical_path: str | None = None
    section_path: str | None = None
    structure_node_id: int | None = None
    structure_node_type: int | None = None
    item_index: int = 0
    document_id: int = 0
