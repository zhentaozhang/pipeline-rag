"""
图查询引擎（Neo4j）
执行 Cypher 语句，检索文档树形结构（Document -> Section -> Chunk/Item）。
"""

import re
from typing import Any

import structlog

from app.common.utils import safe_int
from app.infra.neo4j import get_neo4j
from app.rag.graph.models import GraphItem, GraphQueryResult, GraphSection

logger = structlog.get_logger(__name__)


def _to_dict(node: Any) -> dict:
    """将 Neo4j Node/Record 统一转换为 dict"""
    if isinstance(node, dict):
        return node
    if hasattr(node, "items"):
        return dict(node.items())
    return {}


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[\s>`*#_\-]+", "", text).lower()


def _as_text(node: dict, key: str) -> str:
    val = node.get(key)
    return str(val).strip() if val is not None else ""


def _as_int(node: dict, key: str) -> int | None:
    val = node.get(key)
    return int(val) if val is not None else None


def _neo_node_to_section(n: dict) -> dict:
    """Convert Neo4j node dict to kwargs for GraphSection constructor"""
    return {
        "node_id": n.get("nodeId") or n.get("node_id") or n.get("id", 0),
        "document_id": n.get("documentId") or n.get("document_id") or n.get("doc_id", 0),
        "parse_task_id": _as_int(n, "parseTaskId")
        or _as_int(n, "parse_task_id")
        or _as_int(n, "parseTaskId"),
        "node_no": _as_int(n, "nodeNo") or _as_int(n, "node_no"),
        "depth": _as_int(n, "depth"),
        "parent_node_id": _as_int(n, "parentNodeId") or _as_int(n, "parent_node_id"),
        "prev_sibling_node_id": _as_int(n, "prevSiblingNodeId")
        or _as_int(n, "prev_sibling_node_id"),
        "next_sibling_node_id": _as_int(n, "nextSiblingNodeId")
        or _as_int(n, "next_sibling_node_id"),
        "node_code": _as_text(n, "nodeCode") or _as_text(n, "node_code"),
        "title": _as_text(n, "title"),
        "anchor_text": _as_text(n, "anchorText") or _as_text(n, "anchor_text"),
        "section_path": _as_text(n, "sectionPath") or _as_text(n, "section_path"),
        "canonical_path": _as_text(n, "canonicalPath")
        or _as_text(n, "canonical_path")
        or _as_text(n, "canonicalPath"),
        "content_text": _as_text(n, "contentText") or _as_text(n, "content_text"),
    }


def _neo_node_to_item(n: dict) -> dict:
    """Convert Neo4j node dict to kwargs for GraphItem constructor"""
    return {
        "node_id": n.get("nodeId") or n.get("node_id") or n.get("id", 0),
        "document_id": n.get("documentId") or n.get("document_id") or n.get("doc_id", 0),
        "parse_task_id": _as_int(n, "parseTaskId") or _as_int(n, "parse_task_id"),
        "node_no": _as_int(n, "nodeNo") or _as_int(n, "node_no"),
        "node_type": _as_text(n, "nodeType") or _as_text(n, "node_type"),
        "section_node_id": _as_int(n, "sectionNodeId") or _as_int(n, "section_node_id"),
        "prev_sibling_node_id": _as_int(n, "prevSiblingNodeId")
        or _as_int(n, "prev_sibling_node_id"),
        "next_sibling_node_id": _as_int(n, "nextSiblingNodeId")
        or _as_int(n, "next_sibling_node_id"),
        "title": _as_text(n, "title"),
        "anchor_text": _as_text(n, "anchorText") or _as_text(n, "anchor_text"),
        "section_path": _as_text(n, "sectionPath") or _as_text(n, "section_path"),
        "canonical_path": _as_text(n, "canonicalPath") or _as_text(n, "canonical_path"),
        "content_text": _as_text(n, "contentText") or _as_text(n, "content_text"),
        "item_index": _as_int(n, "itemIndex") or _as_int(n, "item_index"),
    }


class Neo4jGraphService:
    """
     文档结构图谱查询引擎。
     包含 10+ 种精确查询和图导航方法。
     属性名：documentId, nodeId, nodeCode, nodeNo, parentNodeId,
     prevSiblingNodeId, nextSiblingNodeId, normalizedTitle, normalizedPath, contentText。
     """

    async def _run_query(
        self,
        query: str,
        params: dict = None,
        description: str = "query",
        fetch_mode: str = "single",
    ) -> Any:
        """Execute a Neo4j query with session management.
        fetch_mode: 'single' → await result.single() and return dict or False
                    'data' → await result.data() and return list or []
        """
        driver = get_neo4j()
        try:
            async with driver.session() as session:
                result = await session.run(query, **(params or {}))
                if fetch_mode == "single":
                    record = await result.single()
                    return dict(record) if record else False
                elif fetch_mode == "data":
                    return await result.data()
                else:
                    logger.error(
                        "Unknown fetch_mode '%s' in _run_query for %s", fetch_mode, description
                    )
                    return False
        except Exception as e:
            logger.error("Neo4j %s failed: %s", description, str(e), exc_info=True)
            if fetch_mode == "data":
                return []
            return False

    async def is_graph_available(self, doc_id: str) -> bool:
        """检查指定文档在图谱中是否存在。"""
        record = await self._run_query(
            "MATCH (d:Document {documentId: $documentId}) RETURN count(d) > 0 AS available",
            {"documentId": safe_int(doc_id)},
            "is_graph_available",
            fetch_mode="single",
        )
        return record.get("available", False) if record else False

    async def get_document_tree(self, doc_id: str) -> GraphQueryResult | None:
        """获取指定文档的完整树形结构"""
        logger.debug("neo4j query document tree", doc_id=doc_id)
        driver = get_neo4j()

        query = """
        MATCH (d:Document {documentId: $doc_id})-[:HAS_SECTION]->(s:Section)
        RETURN d, collect(s) as sections
        """

        try:
            async with driver.session() as session:
                result = await session.run(query, doc_id=safe_int(doc_id))
                record = await result.single()
                if not record:
                    return None

                doc_node = record["d"]
                sections = record["sections"]

                return GraphQueryResult(
                    doc=_to_dict(doc_node),
                    sections=[
                        GraphSection(**_neo_node_to_section(dict(s.items()))) for s in sections
                    ],
                )
        except Exception as e:
            logger.error("neo4j document tree query failed", error=str(e), exc_info=True)
            return None

    # ── 图谱精确导航 (Graph Navigation API) ─────────────────────────────────

    async def find_section_by_id(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        record = await self._run_query(
            "MATCH (s:Section {documentId: $documentId, nodeId: $nodeId}) RETURN s LIMIT 1",
            {"documentId": safe_int(doc_id), "nodeId": safe_int(section_node_id)},
            "find_section_by_id",
            fetch_mode="single",
        )
        if record:
            n = record["s"]
            return GraphSection(**_neo_node_to_section(_to_dict(n)))
        return None

    async def find_section_by_code(self, doc_id: str, node_code: str) -> GraphSection | None:
        record = await self._run_query(
            "MATCH (s:Section {documentId: $documentId, nodeCode: $nodeCode}) RETURN s ORDER BY s.nodeNo ASC LIMIT 1",
            {"documentId": safe_int(doc_id), "nodeCode": node_code.strip()},
            "find_section_by_code",
            fetch_mode="single",
        )
        if record:
            n = record["s"]
            return GraphSection(**_neo_node_to_section(_to_dict(n)))
        return None

    async def find_section_by_title(self, doc_id: str, title: str) -> GraphSection | None:
        normalized = _normalize(title)
        record = await self._run_query(
            """
        MATCH (s:Section {documentId: $documentId})
        WHERE s.normalizedTitle = $normalized OR s.normalizedPath = $normalized
        RETURN s
        ORDER BY s.nodeNo ASC
        LIMIT 1
        """,
            {"documentId": safe_int(doc_id), "normalized": normalized},
            "find_section_by_title",
            fetch_mode="single",
        )
        if record:
            n = record["s"]
            return GraphSection(**_neo_node_to_section(_to_dict(n)))
        return None

    async def find_section_by_canonical_path(
        self, doc_id: str, canonical_path: str
    ) -> GraphSection | None:
        record = await self._run_query(
            "MATCH (s:Section {documentId: $documentId, canonicalPath: $canonicalPath}) RETURN s LIMIT 1",
            {"documentId": safe_int(doc_id), "canonicalPath": canonical_path.strip()},
            "find_section_by_canonical_path",
            fetch_mode="single",
        )
        if record:
            n = record["s"]
            return GraphSection(**_neo_node_to_section(_to_dict(n)))
        return None

    async def find_best_section(self, doc_id: str, topic: str, facet: str) -> GraphSection | None:
        normalized_topic = _normalize(topic)
        normalized_facet = _normalize(facet)

        driver = get_neo4j()
        query = "MATCH (s:Section {documentId: $documentId}) RETURN s"
        try:
            async with driver.session() as session:
                result = await session.run(query, documentId=safe_int(doc_id))
                records = await result.data()

            best_section = None
            best_score = 0

            for record in records:
                s_dict = _to_dict(record.get("s"))
                score = 0

                title = _normalize(s_dict.get("title", ""))
                section_path = _normalize(
                    s_dict.get("sectionPath", "") or s_dict.get("section_path", "")
                )
                anchor = _normalize(s_dict.get("anchorText", "") or s_dict.get("anchor_text", ""))
                content = _normalize(
                    s_dict.get("contentText", "") or s_dict.get("content_text", "")
                )

                if normalized_topic:
                    if normalized_topic in title or normalized_topic in section_path:
                        score += 8
                    elif normalized_topic in anchor:
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
                    best_section = GraphSection(**_neo_node_to_section(s_dict))

            return best_section if best_score > 0 else None
        except Exception as e:
            logger.error("find_best_section failed", error=str(e), exc_info=True)
            return None

    async def list_sections(self, doc_id: str) -> list[GraphSection]:
        records = await self._run_query(
            "MATCH (s:Section {documentId: $documentId}) RETURN s ORDER BY s.nodeNo ASC",
            {"documentId": safe_int(doc_id)},
            "list_sections",
            fetch_mode="data",
        )
        sections = []
        for record in records:
            if "s" in record:
                n = record["s"]
                sections.append(GraphSection(**_neo_node_to_section(_to_dict(n))))
        return sections

    async def list_children(self, doc_id: str, section_node_id: str) -> list[GraphSection]:
        driver = get_neo4j()
        query = """
        MATCH (:Section {documentId: $documentId, nodeId: $nodeId})-[:HAS_CHILD]->(c:Section {documentId: $documentId})
        RETURN c ORDER BY c.nodeNo ASC
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    nodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                )
                records = await result.data()
                sections = []
                for record in records:
                    if "c" in record:
                        n = record["c"]
                        sections.append(GraphSection(**_neo_node_to_section(_to_dict(n))))
                return sections
        except Exception as e:
            logger.error("list_children failed", error=str(e), exc_info=True)
            return []

    async def parent_section(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        driver = get_neo4j()
        query = """
        MATCH (p:Section {documentId: $documentId})-[:HAS_CHILD]->(:Section {documentId: $documentId, nodeId: $nodeId})
        RETURN p LIMIT 1
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    nodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                )
                record = await result.single()
                if record and "p" in record:
                    n = record["p"]
                    return GraphSection(**_neo_node_to_section(_to_dict(n)))
                return None
        except Exception as e:
            logger.error("parent_section failed", error=str(e), exc_info=True)
            return None

    async def previous_sibling(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        driver = get_neo4j()
        query = """
        MATCH (p:Section {documentId: $documentId})-[:NEXT_SIBLING]->(:Section {documentId: $documentId, nodeId: $nodeId})
        RETURN p LIMIT 1
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    nodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                )
                record = await result.single()
                if record and "p" in record:
                    n = record["p"]
                    return GraphSection(**_neo_node_to_section(_to_dict(n)))
                return None
        except Exception as e:
            logger.error("previous_sibling failed", error=str(e), exc_info=True)
            return None

    async def next_sibling(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        driver = get_neo4j()
        query = """
        MATCH (:Section {documentId: $documentId, nodeId: $nodeId})-[:NEXT_SIBLING]->(n:Section {documentId: $documentId})
        RETURN n LIMIT 1
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    nodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                )
                record = await result.single()
                if record and "n" in record:
                    n = record["n"]
                    return GraphSection(**_neo_node_to_section(_to_dict(n)))
                return None
        except Exception as e:
            logger.error("next_sibling failed", error=str(e), exc_info=True)
            return None

    async def find_item_by_index(
        self, doc_id: str, section_node_id: str, item_index: int
    ) -> GraphItem | None:
        driver = get_neo4j()
        query = """
        MATCH (:Section {documentId: $documentId, nodeId: $sectionNodeId})-[:HAS_ITEM]->(i:Item {documentId: $documentId, itemIndex: $itemIndex})
        RETURN i
        ORDER BY i.nodeNo ASC
        LIMIT 1
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    sectionNodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                    itemIndex=item_index,
                )
                record = await result.single()
                if record:
                    n = record["i"]
                    return GraphItem(**_neo_node_to_item(_to_dict(n)))
                return None
        except Exception as e:
            logger.error("find_item_by_index failed", error=str(e), exc_info=True)
            return None

    async def list_items(self, doc_id: str, section_node_id: str) -> list[GraphItem]:
        driver = get_neo4j()
        query = """
        MATCH (:Section {documentId: $documentId, nodeId: $sectionNodeId})-[:HAS_ITEM]->(i:Item {documentId: $documentId})
        RETURN i ORDER BY i.nodeNo ASC
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    sectionNodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                )
                records = await result.data()
                items = []
                for record in records:
                    if "i" in record:
                        n = record["i"]
                        items.append(GraphItem(**_neo_node_to_item(_to_dict(n))))
                return items
        except Exception as e:
            logger.error("list_items failed", error=str(e), exc_info=True)
            return []

    async def search_items_in_section(
        self, doc_id: str, section_node_id: str, keyword: str
    ) -> list[GraphItem]:
        normalized_keyword = _normalize(keyword)
        driver = get_neo4j()
        query = """
        MATCH (:Section {documentId: $documentId, nodeId: $sectionNodeId})-[:HAS_ITEM]->(i:Item {documentId: $documentId})
        WHERE i.normalizedTitle CONTAINS $keyword OR toLower(coalesce(i.contentText, '')) CONTAINS $keyword
        RETURN i ORDER BY i.nodeNo ASC
        """
        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    sectionNodeId=safe_int(section_node_id),
                    documentId=safe_int(doc_id),
                    keyword=normalized_keyword,
                )
                records = await result.data()
                items = []
                for record in records:
                    if "i" in record:
                        n = record["i"]
                        items.append(GraphItem(**_neo_node_to_item(_to_dict(n))))
                return items
        except Exception as e:
            logger.error("search_items_in_section failed", error=str(e), exc_info=True)
            return []
