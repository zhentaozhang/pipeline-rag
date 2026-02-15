import structlog

from app.document.structure.ambiguity import DocumentStructureAmbiguityResolver
from app.document.structure.extractors import DocumentStructureSignalExtractor
from app.document.structure.hierarchy import DocumentStructureHierarchyResolver
from app.document.structure.models import DocumentStructureNodeCandidate
from app.document.structure.validator import DocumentStructureTreeValidator

logger = structlog.get_logger(__name__)


class DocumentStructurePipeline:
    """文档结构分析流水线 (5-Stage Engine)"""

    def __init__(self) -> None:
        self.signal_extractor = DocumentStructureSignalExtractor()
        self.ambiguity_resolver = DocumentStructureAmbiguityResolver()
        self.hierarchy_resolver = DocumentStructureHierarchyResolver()
        self.tree_validator = DocumentStructureTreeValidator()

    async def extract(
        self, document_title: str, parsed_text: str
    ) -> list[DocumentStructureNodeCandidate]:
        """
        执行完整的 5 阶段文档结构分析
        1. 提取结构信号 (Extraction)
        2. 消除歧义 (Disambiguation)
        3. 构建层级树 (Hierarchy Resolution)
        4. 验证并修复树 (Validation & Repair)
        """
        normalized_title = (document_title or "文档").strip()
        normalized_text = (parsed_text or "").strip()

        if not normalized_text:
            return [
                DocumentStructureNodeCandidate(
                    node_no=1,
                    node_type="document",
                    parent_node_no=None,
                    prev_sibling_node_no=0,
                    next_sibling_node_no=0,
                    depth=0,
                    node_code="",
                    title=normalized_title,
                    anchor_text=normalized_title,
                    canonical_path="/document",
                    section_path="",
                    content_text="",
                    item_index=None,
                )
            ]

        logger.info(
            "Starting document structure extraction",
            title=normalized_title,
            text_length=len(normalized_text),
        )

        # Phase 1: 信号提取
        signal_batch = self.signal_extractor.extract(normalized_title, normalized_text)

        # Phase 2: 上下文歧义消除
        resolved_signals = await self.ambiguity_resolver.resolve(
            normalized_title, signal_batch.context_lines, signal_batch.signals
        )

        # Phase 3: 线性信号映射到层级树草案
        drafts = self.hierarchy_resolver.resolve(normalized_title, resolved_signals)

        # Phase 4 & 5: 验证与最终节点构建
        candidates = self.tree_validator.validate_and_build(normalized_title, drafts)

        logger.info("Document structure extraction completed", candidates_count=len(candidates))
        return candidates
