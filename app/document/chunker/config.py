from dataclasses import dataclass, field


@dataclass
class ChunkConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64
    min_chunk_size: int = 50
    max_chunk_size: int = 1024
    separators: list[str] = field(default_factory=lambda: ["\n\n", "\n", "。", ".", " ", ""])
