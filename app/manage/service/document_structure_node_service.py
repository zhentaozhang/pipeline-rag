"""
文档结构节点持久化服务
负责将内存中的 StructureNodeCandidate 落盘到 MySQL 和 Neo4j 图数据库中
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils import safe_int
from app.config import get_settings
from app.document.structure.models import DocumentStructureNodeCandidate as StructureNodeCandidate

if TYPE_CHECKING:
    from app.db.models.document import DocumentStructureNode
from app.infra.id_generator import next_id
from app.infra.neo4j import get_neo4j

logger = structlog.get_logger(__name__)

_NODE_TYPE_MAP = {
    "document": 0,
    "section": 1,
    "list_item": 2,
    "step": 3,
}


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[\s>`*#_\-]+", "", text).lower()


def _safe_text(text: str | None) -> str:
    return text.strip() if text else ""


async def save_nodes(
    db: AsyncSession, doc_id: str, parse_task_id: str, nodes: list[StructureNodeCandidate]
) -> None:
    """
    保存结构节点到数据库，并同步到 Neo4j 建立图谱拓扑
    """
    if not nodes:
        return

    logger.info(f"saving structure nodes for doc_id={doc_id}, count={len(nodes)}")

    from app.db.models.document import Document as Doc
    from app.db.models.document import DocumentStructureNode as Node

    doc_stmt = select(Doc.id).where(Doc.doc_id == doc_id)
    doc_res = await db.execute(doc_stmt)
    doc_internal_id = doc_res.scalar_one_or_none()
    if doc_internal_id is None:
        logger.error("document not found for saving structure nodes", doc_id=doc_id)
        return

    id_map: dict[int, int] = {}
    for node in nodes:
        db_id = next_id()
        id_map[node.node_no] = db_id
        node.node_id = str(db_id)

    db_entities = []
    for node in nodes:
        db_id = id_map[node.node_no]
        parent_id = id_map.get(node.parent_node_no) if node.parent_node_no else None
        prev_id = id_map.get(node.prev_sibling_node_no) if node.prev_sibling_node_no else None
        next_id_val = id_map.get(node.next_sibling_node_no) if node.next_sibling_node_no else None

        node_type_val = _NODE_TYPE_MAP.get(node.node_type, 0)

        entity = Node(
            id=db_id,
            document_id=doc_internal_id,
            parse_task_id=parse_task_id,
            node_no=node.node_no,
            node_type=node_type_val,
            parent_node_id=parent_id,
            prev_sibling_node_id=prev_id,
            next_sibling_node_id=next_id_val,
            depth=node.depth,
            node_code=node.node_code,
            title=node.title,
            anchor_text=node.anchor_text,
            canonical_path=node.canonical_path,
            section_path=node.section_path,
            content_text=node.content_text,
            item_index=node.item_index,
            status=1,
        )
        db_entities.append(entity)

    db.add_all(db_entities)
    try:
        await db.flush()
        logger.info("mysql save nodes success", doc_id=doc_id, count=len(db_entities))
    except Exception as e:
        logger.error("failed to save nodes to mysql", error=str(e))
        return

    if get_settings().neo4j.enabled:
        await _sync_to_neo4j(doc_id, db_entities)
    else:
        logger.info("neo4j sync skipped (disabled by config)", doc_id=doc_id)

    from app.document.navigation_indexer import NavigationIndexer

    nav_indexer = NavigationIndexer()
    try:
        await nav_indexer.index_nodes(doc_id, parse_task_id, db_entities)
    except Exception as e:
        logger.error("failed to sync nodes to navigation index", error=str(e))


async def _sync_to_neo4j(doc_id: str, db_nodes: list[DocumentStructureNode]) -> None:
    """
    同步节点和关系到 Neo4j。
    Neo4j 图结构投影同步：
    - Document 节点 + documentName + parseTaskId + currentVersion
    - Section 节点: 所有字段 + parseTaskId + normalizedTitle + normalizedPath
    - Item 节点: 所有字段 + parseTaskId + normalizedTitle
    - Document -[:HAS_SECTION]-> Section; Section -[:BELONGS_TO_DOCUMENT]-> Document
    - Section -[:HAS_CHILD]-> Section
    - Section -[:HAS_ITEM]-> Item; Item -[:BELONGS_TO_SECTION]-> Section
    - NEXT_SIBLING / PREV_SIBLING (Section); NEXT_ITEM / PREV_ITEM (Item)
    """
    driver = get_neo4j()
    get_settings()

    document_name = ""
    try:
        from app.db.models.document import Document as DocModel
        from app.db.session import _session_factory as async_session_maker

        if async_session_maker is None:
            raise RuntimeError("db session factory not initialized")
        async with async_session_maker() as db:
            stmt = select(DocModel.document_name).where(DocModel.doc_id == doc_id)
            res = await db.execute(stmt)
            row = res.scalar_one_or_none()
            if row:
                document_name = _safe_text(row)
    except Exception as e:
        logger.warning("failed to fetch document name", doc_id=doc_id, error=str(e))

    db_doc_id = safe_int(doc_id)

    try:
        async with driver.session() as session:
            # 1. 删除已存在的文档图谱
            await session.run(
                """
                    MATCH (n)
                    WHERE (n:Document OR n:Section OR n:Item) AND n.documentId = $documentId
                    DETACH DELETE n
                """,
                documentId=db_doc_id,
            )

            # 2. 创建 Document 节点 (含 parseTaskId + currentVersion)
            parse_task_val = 0
            if db_nodes and db_nodes[0].parse_task_id:
                raw_task_id = db_nodes[0].parse_task_id
                parsed_task_id = (
                    safe_int(raw_task_id, default=None) if raw_task_id is not None else None
                )
                parse_task_val = parsed_task_id if parsed_task_id is not None else 0
            await session.run(
                """
                    CREATE (d:Document {
                      documentId: $documentId,
                      documentName: $documentName,
                      parseTaskId: $parseTaskId,
                      currentVersion: $parseTaskId
                    })
                """,
                documentId=db_doc_id,
                documentName=document_name,
                parseTaskId=parse_task_val,
            )

            # 3. 创建 Section / Item 节点 (跳过 DOCUMENT 类型节点)
            #    _NODE_TYPE_MAP: document=0, section=1, list_item=2, step=3
            for n in db_nodes:
                if n.id is None:
                    continue
                if n.node_type == 0:
                    # DOCUMENT type — 不投影到 Neo4j (已在步骤2创建)
                    continue
                if n.node_type == 1:
                    # Section 节点 (含 parseTaskId)
                    await session.run(
                        """
                            CREATE (s:Section {
                              nodeId: $nodeId,
                              documentId: $documentId,
                              parseTaskId: $parseTaskId,
                              nodeNo: $nodeNo,
                              depth: $depth,
                              parentNodeId: $parentNodeId,
                              prevSiblingNodeId: $prevSiblingNodeId,
                              nextSiblingNodeId: $nextSiblingNodeId,
                              nodeCode: $nodeCode,
                              title: $title,
                              anchorText: $anchorText,
                              sectionPath: $sectionPath,
                              canonicalPath: $canonicalPath,
                              contentText: $contentText,
                              normalizedTitle: $normalizedTitle,
                              normalizedPath: $normalizedPath
                            })
                        """,
                        {
                            "nodeId": n.id,
                            "documentId": db_doc_id,
                            "parseTaskId": parse_task_val,
                            "nodeNo": n.node_no or 0,
                            "depth": n.depth or 0,
                            "parentNodeId": n.parent_node_id,
                            "prevSiblingNodeId": n.prev_sibling_node_id,
                            "nextSiblingNodeId": n.next_sibling_node_id,
                            "nodeCode": _safe_text(n.node_code),
                            "title": _safe_text(n.title),
                            "anchorText": _safe_text(n.anchor_text),
                            "sectionPath": _safe_text(n.section_path),
                            "canonicalPath": _safe_text(n.canonical_path),
                            "contentText": _safe_text(n.content_text),
                            "normalizedTitle": _normalize(n.title),
                            "normalizedPath": _normalize(n.section_path),
                        },
                    )
                else:
                    # Item 节点 (STEP / LIST_ITEM，含 parseTaskId + depth)
                    item_node_type = "STEP" if n.node_type == 3 else "LIST_ITEM"
                    await session.run(
                        """
                            CREATE (i:Item {
                              nodeId: $nodeId,
                              documentId: $documentId,
                              parseTaskId: $parseTaskId,
                              nodeNo: $nodeNo,
                              nodeType: $nodeType,
                              depth: $depth,
                              sectionNodeId: $sectionNodeId,
                              prevSiblingNodeId: $prevSiblingNodeId,
                              nextSiblingNodeId: $nextSiblingNodeId,
                              title: $title,
                              anchorText: $anchorText,
                              sectionPath: $sectionPath,
                              canonicalPath: $canonicalPath,
                              contentText: $contentText,
                              itemIndex: $itemIndex,
                              normalizedTitle: $normalizedTitle
                            })
                        """,
                        {
                            "nodeId": n.id,
                            "documentId": db_doc_id,
                            "parseTaskId": parse_task_val,
                            "nodeNo": n.node_no or 0,
                            "nodeType": item_node_type,
                            "depth": n.depth or 0,
                            "sectionNodeId": n.parent_node_id,
                            "prevSiblingNodeId": n.prev_sibling_node_id,
                            "nextSiblingNodeId": n.next_sibling_node_id,
                            "title": _safe_text(n.title),
                            "anchorText": _safe_text(n.anchor_text),
                            "sectionPath": _safe_text(n.section_path),
                            "canonicalPath": _safe_text(n.canonical_path),
                            "contentText": _safe_text(n.content_text),
                            "itemIndex": n.item_index,
                            "normalizedTitle": _normalize(n.title),
                        },
                    )

            # 4. 创建关系
            for n in db_nodes:
                if n.id is None:
                    continue
                if n.node_type == 0:
                    # DOCUMENT type — skip
                    continue
                if n.node_type == 1:
                    if n.parent_node_id is None:
                        # Document -> Section
                        await session.run(
                            """
                                MATCH (d:Document {documentId: $documentId}),
                                      (s:Section {documentId: $documentId, nodeId: $nodeId})
                                MERGE (d)-[:HAS_SECTION]->(s)
                                MERGE (s)-[:BELONGS_TO_DOCUMENT]->(d)
                            """,
                            documentId=db_doc_id,
                            nodeId=n.id,
                        )
                    else:
                        # Section -> child Section
                        await session.run(
                            """
                                MATCH (p:Section {documentId: $documentId, nodeId: $parentNodeId}),
                                      (s:Section {documentId: $documentId, nodeId: $nodeId})
                                MERGE (p)-[:HAS_CHILD]->(s)
                            """,
                            documentId=db_doc_id,
                            parentNodeId=n.parent_node_id,
                            nodeId=n.id,
                        )

                    # Section sibling edges
                    if n.next_sibling_node_id is not None:
                        await session.run(
                            """
                                MATCH (a:Section {documentId: $documentId, nodeId: $nodeId}),
                                      (b:Section {documentId: $documentId, nodeId: $nextNodeId})
                                MERGE (a)-[:NEXT_SIBLING]->(b)
                                MERGE (b)-[:PREV_SIBLING]->(a)
                            """,
                            documentId=db_doc_id,
                            nodeId=n.id,
                            nextNodeId=n.next_sibling_node_id,
                        )
                    elif n.prev_sibling_node_id is not None:
                        await session.run(
                            """
                                MATCH (a:Section {documentId: $documentId, nodeId: $prevNodeId}),
                                      (b:Section {documentId: $documentId, nodeId: $nodeId})
                                MERGE (a)-[:NEXT_SIBLING]->(b)
                                MERGE (b)-[:PREV_SIBLING]->(a)
                            """,
                            documentId=db_doc_id,
                            prevNodeId=n.prev_sibling_node_id,
                            nodeId=n.id,
                        )
                else:
                    # Section -> Item
                    await session.run(
                        """
                            MATCH (s:Section {documentId: $documentId, nodeId: $sectionNodeId}),
                                  (i:Item {documentId: $documentId, nodeId: $nodeId})
                            MERGE (s)-[:HAS_ITEM]->(i)
                            MERGE (i)-[:BELONGS_TO_SECTION]->(s)
                        """,
                        documentId=db_doc_id,
                        sectionNodeId=n.parent_node_id,
                        nodeId=n.id,
                    )

                    # Item sibling edges
                    if n.next_sibling_node_id is not None:
                        await session.run(
                            """
                                MATCH (a:Item {documentId: $documentId, nodeId: $nodeId}),
                                      (b:Item {documentId: $documentId, nodeId: $nextNodeId})
                                MERGE (a)-[:NEXT_ITEM]->(b)
                                MERGE (b)-[:PREV_ITEM]->(a)
                            """,
                            documentId=db_doc_id,
                            nodeId=n.id,
                            nextNodeId=n.next_sibling_node_id,
                        )
                    elif n.prev_sibling_node_id is not None:
                        await session.run(
                            """
                                MATCH (a:Item {documentId: $documentId, nodeId: $prevNodeId}),
                                      (b:Item {documentId: $documentId, nodeId: $nodeId})
                                MERGE (a)-[:NEXT_ITEM]->(b)
                                MERGE (b)-[:PREV_ITEM]->(a)
                            """,
                            documentId=db_doc_id,
                            prevNodeId=n.prev_sibling_node_id,
                            nodeId=n.id,
                        )

            # 5. 创建索引 (needed for query performance)
            await session.run(
                "CREATE INDEX document_document_id IF NOT EXISTS FOR (d:Document) ON (d.documentId)"
            )
            await session.run(
                "CREATE INDEX section_node_id IF NOT EXISTS FOR (s:Section) ON (s.nodeId)"
            )
            await session.run(
                "CREATE INDEX section_document_id IF NOT EXISTS FOR (s:Section) ON (s.documentId)"
            )
            await session.run(
                "CREATE INDEX section_document_node_id IF NOT EXISTS FOR (s:Section) ON (s.documentId, s.nodeId)"
            )
            await session.run(
                "CREATE INDEX section_node_code IF NOT EXISTS FOR (s:Section) ON (s.documentId, s.nodeCode)"
            )
            await session.run(
                "CREATE INDEX section_title IF NOT EXISTS FOR (s:Section) ON (s.documentId, s.normalizedTitle)"
            )
            await session.run("CREATE INDEX item_node_id IF NOT EXISTS FOR (i:Item) ON (i.nodeId)")
            await session.run(
                "CREATE INDEX item_document_node_id IF NOT EXISTS FOR (i:Item) ON (i.documentId, i.nodeId)"
            )
            await session.run(
                "CREATE INDEX item_index IF NOT EXISTS FOR (i:Item) ON (i.documentId, i.sectionPath, i.itemIndex)"
            )

        logger.info("neo4j sync nodes success", doc_id=doc_id)

        # 索引创建（独立处理，失败不影响节点同步）
        try:
            await session.run(
                "CREATE INDEX document_document_id IF NOT EXISTS FOR (d:Document) ON (d.documentId)"
            )
            await session.run(
                "CREATE INDEX section_node_id IF NOT EXISTS FOR (s:Section) ON (s.nodeId)"
            )
            await session.run(
                "CREATE INDEX section_document_id IF NOT EXISTS FOR (s:Section) ON (s.documentId)"
            )
            await session.run(
                "CREATE INDEX section_document_node_id IF NOT EXISTS FOR (s:Section) ON (s.documentId, s.nodeId)"
            )
            await session.run(
                "CREATE INDEX section_node_code IF NOT EXISTS FOR (s:Section) ON (s.documentId, s.nodeCode)"
            )
            await session.run(
                "CREATE INDEX section_title IF NOT EXISTS FOR (s:Section) ON (s.documentId, s.normalizedTitle)"
            )
            await session.run("CREATE INDEX item_node_id IF NOT EXISTS FOR (i:Item) ON (i.nodeId)")
            await session.run(
                "CREATE INDEX item_document_node_id IF NOT EXISTS FOR (i:Item) ON (i.documentId, i.nodeId)"
            )
            await session.run(
                "CREATE INDEX item_index IF NOT EXISTS FOR (i:Item) ON (i.documentId, i.sectionPath, i.itemIndex)"
            )
        except Exception as index_err:
            logger.warning("neo4j index creation failed", error=str(index_err))

    except Exception as e:
        logger.error("failed to sync nodes to neo4j", error=str(e))


async def list_structure_nodes(db: AsyncSession, doc_id: str) -> list[dict]:
    from app.db.models.document import Document as Doc
    from app.db.models.document import DocumentStructureNode as Node

    stmt = (
        select(Node)
        .join(Doc, Doc.id == Node.document_id)
        .where(Doc.doc_id == doc_id)
        .order_by(Node.node_no)
    )
    result = await db.execute(stmt)
    nodes = result.scalars().all()
    return [
        {
            "id": n.id,
            "node_no": n.node_no,
            "node_type": n.node_type,
            "parent_node_id": n.parent_node_id,
            "depth": n.depth,
            "node_code": n.node_code,
            "title": n.title,
            "anchor_text": n.anchor_text,
            "canonical_path": n.canonical_path,
            "section_path": n.section_path,
            "item_index": n.item_index,
            "status": n.status,
        }
        for n in nodes
    ]


async def get_structure_graph(db: AsyncSession, doc_id: str) -> tuple[list[dict], list[dict]]:
    from app.db.models.document import Document as Doc
    from app.db.models.document import DocumentStructureNode as Node

    stmt = (
        select(Node)
        .join(Doc, Doc.id == Node.document_id)
        .where(Doc.doc_id == doc_id)
        .order_by(Node.node_no)
    )
    result = await db.execute(stmt)
    nodes = result.scalars().all()

    node_list = []
    edge_list = []
    for n in nodes:
        node_list.append(
            {
                "id": n.id,
                "node_no": n.node_no,
                "node_type": n.node_type,
                "parent_node_id": n.parent_node_id,
                "depth": n.depth,
                "node_code": n.node_code,
                "title": n.title,
                "anchor_text": n.anchor_text,
                "canonical_path": n.canonical_path,
                "section_path": n.section_path,
                "item_index": n.item_index,
                "status": n.status,
            }
        )
        if n.parent_node_id:
            rel_type = "HAS_ITEM" if n.node_type == 1 else "HAS_SECTION"
            edge_list.append(
                {
                    "parent_id": n.parent_node_id,
                    "child_id": n.id,
                    "rel_type": rel_type,
                }
            )
    return node_list, edge_list
