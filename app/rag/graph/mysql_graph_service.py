"""
MySQL 降级图查询引擎
实现文档结构树的 SQL 查询逻辑，提供和 Neo4j 相同的 API，作为系统的高可用底线。
"""

import re

import structlog
from sqlalchemy import select

from app.db.models.document import DocumentStructureNode
from app.db.session import _session_factory as async_session_maker
from app.rag.graph.models import GraphItem, GraphQueryResult, GraphSection

logger = structlog.get_logger(__name__)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[\s>`*#_\-]+", "", text).lower()


def _safe_text(text: str | None) -> str:
    return text.strip() if text else ""


class MysqlGraphService:
    def _to_section(self, node: DocumentStructureNode) -> GraphSection:
        return GraphSection(
            node_id=node.id,
            document_id=node.document_id,
            parse_task_id=node.parse_task_id,
            node_no=node.node_no,
            depth=node.depth,
            parent_node_id=node.parent_node_id,
            prev_sibling_node_id=node.prev_sibling_node_id,
            next_sibling_node_id=node.next_sibling_node_id,
            node_code=_safe_text(node.node_code),
            title=_safe_text(node.title),
            anchor_text=_safe_text(node.anchor_text),
            section_path=_safe_text(node.section_path),
            canonical_path=_safe_text(node.canonical_path),
            content_text=_safe_text(node.content_text),
        )

    def _to_item(self, node: DocumentStructureNode) -> GraphItem:
        node_type_name = {3: "STEP", 4: "LIST_ITEM"}.get(node.node_type, "")
        return GraphItem(
            node_id=node.id,
            document_id=node.document_id,
            parse_task_id=node.parse_task_id,
            node_no=node.node_no,
            node_type=node_type_name,
            section_node_id=node.parent_node_id,
            prev_sibling_node_id=node.prev_sibling_node_id,
            next_sibling_node_id=node.next_sibling_node_id,
            title=_safe_text(node.title),
            anchor_text=_safe_text(node.anchor_text),
            section_path=_safe_text(node.section_path),
            canonical_path=_safe_text(node.canonical_path),
            content_text=_safe_text(node.content_text),
            item_index=node.item_index,
        )

    async def get_document_tree(self, doc_id: str) -> GraphQueryResult | None:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.document_id == doc_id,
                    DocumentStructureNode.node_type == 2,
                )
                .order_by(DocumentStructureNode.node_no)
            )
            res = await db.execute(stmt)
            nodes = res.scalars().all()
            if not nodes:
                return None
            return GraphQueryResult(
                doc={"doc_id": doc_id}, sections=[self._to_section(n) for n in nodes]
            )

    async def find_section_by_id(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt = select(DocumentStructureNode).where(
                DocumentStructureNode.id == int(section_node_id),
                DocumentStructureNode.document_id == doc_id,
            )
            res = await db.execute(stmt)
            node = res.scalar_one_or_none()
            return self._to_section(node) if node else None

    async def find_section_by_code(self, doc_id: str, node_code: str) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.node_code == node_code.strip(),
                    DocumentStructureNode.document_id == doc_id,
                )
                .limit(1)
            )
            res = await db.execute(stmt)
            node = res.scalar_one_or_none()
            return self._to_section(node) if node else None

    async def find_section_by_title(self, doc_id: str, title: str) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt = select(DocumentStructureNode).where(DocumentStructureNode.document_id == doc_id)
            res = await db.execute(stmt)
            nodes = res.scalars().all()

            normalized_title = _normalize(title)
            for node in nodes:
                if (
                    normalized_title == _normalize(node.title)
                    or normalized_title == _normalize(node.anchor_text)
                    or normalized_title == _normalize(node.section_path)
                ):
                    return self._to_section(node)
            return None

    async def find_section_by_canonical_path(
        self, doc_id: str, canonical_path: str
    ) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.canonical_path == canonical_path.strip(),
                    DocumentStructureNode.document_id == doc_id,
                )
                .limit(1)
            )
            res = await db.execute(stmt)
            node = res.scalar_one_or_none()
            return self._to_section(node) if node else None

    async def find_best_section(self, doc_id: str, topic: str, facet: str) -> GraphSection | None:
        normalized_topic = _normalize(topic)
        normalized_facet = _normalize(facet)

        async with async_session_maker() as db:
            stmt = select(DocumentStructureNode).where(DocumentStructureNode.document_id == doc_id)
            res = await db.execute(stmt)
            nodes = res.scalars().all()

            best_section = None
            best_score = 0

            for node in nodes:
                score = 0
                section_path = _normalize(node.section_path)
                title = _normalize(node.title)
                anchor_text = _normalize(node.anchor_text)
                content = _normalize(node.content_text)

                if normalized_topic:
                    if normalized_topic in title or normalized_topic in section_path:
                        score += 8
                    elif normalized_topic in anchor_text:
                        score += 6
                    elif normalized_topic in content:
                        score += 2

                if normalized_facet:
                    if normalized_facet in title or normalized_facet in section_path:
                        score += 5
                    elif normalized_facet in content:
                        score += 1

                if score > best_score:
                    best_score = score
                    best_section = self._to_section(node)

            return best_section if best_score > 0 else None

    async def list_sections(self, doc_id: str) -> list[GraphSection]:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.document_id == doc_id,
                    DocumentStructureNode.node_type == 2,
                )
                .order_by(DocumentStructureNode.node_no)
            )
            res = await db.execute(stmt)
            nodes = res.scalars().all()
            return [self._to_section(n) for n in nodes]

    async def list_children(self, doc_id: str, section_node_id: str) -> list[GraphSection]:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.parent_node_id == int(section_node_id),
                    DocumentStructureNode.document_id == doc_id,
                    DocumentStructureNode.node_type == 2,
                )
                .order_by(DocumentStructureNode.node_no)
            )
            res = await db.execute(stmt)
            nodes = res.scalars().all()
            return [self._to_section(n) for n in nodes]

    async def parent_section(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt1 = select(DocumentStructureNode.parent_node_id).where(
                DocumentStructureNode.id == int(section_node_id)
            )
            res1 = await db.execute(stmt1)
            parent_id = res1.scalar_one_or_none()
            if not parent_id:
                return None

            stmt2 = select(DocumentStructureNode).where(DocumentStructureNode.id == parent_id)
            res2 = await db.execute(stmt2)
            parent_node = res2.scalar_one_or_none()
            return self._to_section(parent_node) if parent_node else None

    async def previous_sibling(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt1 = select(DocumentStructureNode.prev_sibling_node_id).where(
                DocumentStructureNode.id == int(section_node_id)
            )
            res1 = await db.execute(stmt1)
            prev_id = res1.scalar_one_or_none()
            if not prev_id:
                return None

            stmt2 = select(DocumentStructureNode).where(DocumentStructureNode.id == prev_id)
            res2 = await db.execute(stmt2)
            node = res2.scalar_one_or_none()
            return self._to_section(node) if node else None

    async def next_sibling(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        async with async_session_maker() as db:
            stmt1 = select(DocumentStructureNode.next_sibling_node_id).where(
                DocumentStructureNode.id == int(section_node_id)
            )
            res1 = await db.execute(stmt1)
            next_id = res1.scalar_one_or_none()
            if not next_id:
                return None

            stmt2 = select(DocumentStructureNode).where(DocumentStructureNode.id == next_id)
            res2 = await db.execute(stmt2)
            node = res2.scalar_one_or_none()
            return self._to_section(node) if node else None

    async def find_item_by_index(
        self, doc_id: str, section_node_id: str, item_index: int
    ) -> GraphItem | None:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.parent_node_id == int(section_node_id),
                    DocumentStructureNode.document_id == doc_id,
                    DocumentStructureNode.node_type.in_([3, 4]),
                    DocumentStructureNode.item_index == item_index,
                )
                .order_by(DocumentStructureNode.node_no)
                .limit(1)
            )
            res = await db.execute(stmt)
            node = res.scalar_one_or_none()
            return self._to_item(node) if node else None

    async def list_items(self, doc_id: str, section_node_id: str) -> list[GraphItem]:
        async with async_session_maker() as db:
            stmt = (
                select(DocumentStructureNode)
                .where(
                    DocumentStructureNode.parent_node_id == int(section_node_id),
                    DocumentStructureNode.document_id == doc_id,
                    DocumentStructureNode.node_type.in_([3, 4]),
                )
                .order_by(DocumentStructureNode.node_no)
            )
            res = await db.execute(stmt)
            nodes = res.scalars().all()
            return [self._to_item(n) for n in nodes]

    async def search_items_in_section(
        self, doc_id: str, section_node_id: str, keyword: str
    ) -> list[GraphItem]:
        items = await self.list_items(doc_id, section_node_id)
        if not items:
            return []

        normalized_keyword = _normalize(keyword)
        if not normalized_keyword:
            return items

        matched = []
        for item in items:
            haystack = _normalize(
                " ".join(
                    [
                        _safe_text(item.title),
                        _safe_text(item.anchor_text),
                        _safe_text(item.content_text),
                    ]
                )
            )
            if normalized_keyword in haystack:
                matched.append(item)

        return matched
