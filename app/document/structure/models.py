from dataclasses import dataclass, field
from enum import StrEnum


class DocumentStructureNodeType(StrEnum):
    DOCUMENT = "document"
    SECTION = "section"
    LIST_ITEM = "list_item"
    STEP = "step"


class DocumentStructureSignalKind(StrEnum):
    BLANK = "BLANK"
    NOISE = "NOISE"
    DOCUMENT_TITLE = "DOCUMENT_TITLE"
    HEADING = "HEADING"
    HEADING_CANDIDATE = "HEADING_CANDIDATE"
    STEP_ITEM = "STEP_ITEM"
    LIST_ITEM = "LIST_ITEM"
    QUOTE = "QUOTE"
    TABLE_ROW = "TABLE_ROW"
    BODY = "BODY"


@dataclass
class DocumentStructureLogicalLine:
    """逻辑行表示（处理了内联切分后的行）"""

    line_no: int
    raw_line_index: int
    segment_index: int
    indent_level: int
    raw_text: str
    normalized_text: str


@dataclass
class DocumentStructureSignal:
    """提取出的结构信号"""

    line_no: int
    raw_text: str
    normalized_text: str
    kind: DocumentStructureSignalKind
    node_code: str = ""
    title: str = ""
    level_hint: int | None = None
    indent_level: int | None = None
    item_index: int | None = None
    reasons: list[str] = field(default_factory=list)
    confidence: float = 1.0
    numeric_path: list[int] | None = None

    @property
    def is_ambiguous(self) -> bool:
        return self.kind == DocumentStructureSignalKind.HEADING_CANDIDATE


@dataclass
class DocumentStructureSignalBatch:
    """批量信号（含上下文）"""

    context_lines: list[str]
    signals: list[DocumentStructureSignal]


@dataclass
class DocumentStructureNodeDraft:
    """解析过程中构建的节点草稿树"""

    node_no: int = 1
    line_no: int = 0
    node_type: str = DocumentStructureNodeType.DOCUMENT.value
    parent_node_no: int | None = None
    prev_sibling_node_no: int | None = None
    next_sibling_node_no: int | None = None
    depth: int = 0
    node_code: str = ""
    title: str = ""
    anchor_text: str = ""
    numeric_path: list[int] = field(default_factory=list)
    source_family: str = ""
    confidence: float = 1.0
    item_index: int | None = None
    canonical_path: str | None = None
    section_path: str | None = None
    _content_lines: list[str] = field(default_factory=list)

    @property
    def is_section(self) -> bool:
        return self.node_type == DocumentStructureNodeType.SECTION.value

    @property
    def is_list_like(self) -> bool:
        return self.node_type in (
            DocumentStructureNodeType.LIST_ITEM.value,
            DocumentStructureNodeType.STEP.value,
        )

    def append_line(self, line: str):
        normalized = (line or "").strip()
        if not normalized:
            return
        self._content_lines.append(normalized)

    def content_text(self) -> str:
        return "\n".join(self._content_lines)


@dataclass
class DocumentStructureNodeCandidate:
    """最终产出的结构节点"""

    node_no: int
    node_type: str
    parent_node_no: int | None
    prev_sibling_node_no: int
    next_sibling_node_no: int
    depth: int
    node_code: str
    title: str
    anchor_text: str
    canonical_path: str
    section_path: str
    content_text: str
    item_index: int | None
    node_id: str | None = None
