from dataclasses import dataclass, field


@dataclass
class ChunkConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64
    min_chunk_size: int = 50
    max_chunk_size: int = 1024
    separators: list[str] = field(default_factory=lambda: ["\n\n", "\n", "。", ".", " ", ""])
    # P0-2 粒度校准：把结构解析产生的相邻小节点合并到目标 token 窗口。
    # 默认关（False）→ 每个节点一块，行为与历史完全一致。
    merge_small_sections: bool = False
    merge_target_tokens: int = 320
    merge_max_tokens: int = 512
