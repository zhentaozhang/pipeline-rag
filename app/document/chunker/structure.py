import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk
from app.document.chunker.utils import count_tokens, make_chunk_id

logger = structlog.get_logger(__name__)


class StructureChunker:
    _NODE_TYPE_MAP = {1: "document", 2: "section", 3: "step", 4: "list_item"}
    _NODE_TYPE_REVERSE = {"document": 1, "section": 2, "step": 3, "list_item": 4}

    @staticmethod
    def _merge_groups(candidates, target_tokens: int, max_tokens: int) -> list[list]:
        """P0-2：把按 node_no 排序的相邻小节点贪心合并到目标 token 窗口。

        - 累计到 target 即封组；再加会超过 max 时强制封组；
        - 单个节点本身已超 max 时单独成组（不切分）；
        - 不改写节点自身，只返回分组。
        纯函数，便于离线单测。
        """
        groups: list[list] = []
        buf: list = []
        buf_tokens = 0
        for cand in candidates:
            t = count_tokens((cand.content_text or "").strip())
            if buf and buf_tokens + t > max_tokens:
                groups.append(buf)
                buf, buf_tokens = [], 0
            buf.append(cand)
            buf_tokens += t
            if buf_tokens >= target_tokens:
                groups.append(buf)
                buf, buf_tokens = [], 0
        if buf:
            groups.append(buf)
        return groups

    async def chunk(self, text: str, doc_id: str, config: ChunkConfig) -> list[Chunk]:
        from sqlalchemy import select

        from app.db.models.document import Document, DocumentStructureNode
        from app.db.session import _session_factory as mysql_session_factory

        if mysql_session_factory is None:
            logger.warning("db session factory not initialized, skip structure chunking")
            return []

        candidates = []
        try:
            async with mysql_session_factory() as session:
                doc_stmt = select(Document.id).where(Document.doc_id == doc_id)
                doc_res = await session.execute(doc_stmt)
                doc_internal_id = doc_res.scalar_one_or_none()
                if doc_internal_id is None:
                    logger.warning("document not found for structure chunking", doc_id=doc_id)
                    return []
                stmt = (
                    select(DocumentStructureNode)
                    .where(DocumentStructureNode.document_id == doc_internal_id)
                    .order_by(DocumentStructureNode.node_no)
                )
                nodes = (await session.execute(stmt)).scalars().all()
                for n in nodes:
                    from app.document.structure.models import DocumentStructureNodeCandidate

                    candidates.append(
                        DocumentStructureNodeCandidate(
                            node_no=n.node_no,
                            node_type=self._NODE_TYPE_MAP.get(n.node_type, "section"),
                            parent_node_no=None,
                            prev_sibling_node_no=0,
                            next_sibling_node_no=0,
                            depth=n.depth,
                            node_code=n.node_code or "",
                            title=n.title or "",
                            anchor_text=n.anchor_text or "",
                            canonical_path=n.canonical_path or "",
                            section_path=n.section_path or "",
                            content_text=n.content_text or "",
                            item_index=n.item_index,
                            node_id=str(n.id),
                        )
                    )
        except Exception as e:
            logger.error("failed to load document structure nodes", error=str(e), exc_info=True)

        if getattr(config, "merge_small_sections", False):
            groups = self._merge_groups(
                candidates,
                int(getattr(config, "merge_target_tokens", 320) or 320),
                int(getattr(config, "merge_max_tokens", 512) or 512),
            )
        else:
            # 默认：每个节点一块（历史行为）
            groups = [[c] for c in candidates]

        results: list[Chunk] = []
        for group in groups:
            txt = "\n".join(
                c.content_text.strip() for c in group if (c.content_text or "").strip()
            ).strip()
            if not txt or len(txt) < config.min_chunk_size:
                continue

            head = group[0]
            results.append(
                Chunk(
                    chunk_id=make_chunk_id(doc_id, txt, len(results), "parent"),
                    doc_id=doc_id,
                    content=txt,
                    chunk_index=len(results),
                    chunk_type="parent",
                    section_title=head.title if head.title else None,
                    token_count=count_tokens(txt),
                    canonical_path=head.canonical_path,
                    section_path=head.section_path,
                    structure_node_id=int(head.node_id) if head.node_id else None,
                    structure_node_type=self._NODE_TYPE_REVERSE.get(head.node_type, 2),
                    item_index=head.item_index or 0,
                )
            )

        logger.debug("structure chunker", count=len(results))
        return results
