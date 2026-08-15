import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk
from app.document.chunker.utils import count_tokens

logger = structlog.get_logger(__name__)


class StructureChunker:
    _NODE_TYPE_MAP = {1: "document", 2: "section", 3: "step", 4: "list_item"}
    _NODE_TYPE_REVERSE = {"document": 1, "section": 2, "step": 3, "list_item": 4}

    async def chunk(self, text: str, doc_id: str, config: ChunkConfig) -> list[Chunk]:
        from sqlalchemy import select

        from app.db.models.document import Document, DocumentStructureNode
        from app.db.session import _session_factory as mysql_session_factory
        from app.infra.id_generator import next_id_str

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

        results = []
        for i, candidate in enumerate(candidates):
            txt = candidate.content_text.strip()
            if not txt or len(txt) < config.min_chunk_size:
                continue

            results.append(
                Chunk(
                    chunk_id=next_id_str(),
                    doc_id=doc_id,
                    content=txt,
                    chunk_index=i,
                    chunk_type="parent",
                    section_title=candidate.title if candidate.title else None,
                    token_count=count_tokens(txt),
                    canonical_path=candidate.canonical_path,
                    section_path=candidate.section_path,
                    structure_node_id=int(candidate.node_id) if candidate.node_id else None,
                    structure_node_type=self._NODE_TYPE_REVERSE.get(candidate.node_type, 2),
                    item_index=candidate.item_index or 0,
                )
            )

        logger.debug("structure chunker", count=len(results))
        return results
