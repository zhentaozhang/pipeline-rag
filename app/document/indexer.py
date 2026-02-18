"""
双引擎索引写入
同时将 Chunk 写入 PGVector（向量）+ ES（关键词），建立双通道检索基础
"""

import structlog

from app.common.utils import safe_int
from app.document.chunker import Chunk
from app.infra.es import CHUNK_INDEX, get_es

logger = structlog.get_logger(__name__)


class DocumentIndexer:
    """
    双引擎索引器：ES 关键词索引 + PGVector 向量索引。
    将文档切片写入 Elasticsearch (全文索引) 和 Neo4j (知识图谱)。
    """

    async def index_to_es(
        self,
        chunks: list[Chunk],
        doc_title: str = "",
        scope_code: str = "",
        scope_name: str = "",
        business_category: str = "",
        document_tags: str = "",
        tenant_id: str = "default",
        task_id: str = "",
    ) -> int:
        """批量写入 Elasticsearch（IK 分词索引）"""
        es = get_es()
        from typing import Any

        # 清理该文档的旧 ES 索引，避免 pipeline 重跑后累积重复
        doc_id = safe_int(chunks[0].doc_id, default=None) if chunks else None
        if doc_id:
            await es.delete_by_query(
                index=CHUNK_INDEX,
                body={"query": {"term": {"documentId": doc_id}}},
                refresh=True,
            )

        child_chunks = [c for c in chunks if c.chunk_type == "child"]
        docs: list[dict[str, Any]] = []

        for chunk in child_chunks:
            docs.append({"index": {"_index": CHUNK_INDEX, "_id": chunk.chunk_id}})
            docs.append(
                {
                    "chunkId": chunk.chunk_id,
                    "tenantId": tenant_id,
                    "documentId": safe_int(chunk.doc_id),
                    "taskId": safe_int(task_id),
                    "chunkNo": chunk.chunk_index,
                    "documentName": doc_title,
                    "sectionPath": chunk.section_path,
                    "structureNodeId": safe_int(chunk.structure_node_id),
                    "structureNodeType": chunk.structure_node_type
                    if chunk.structure_node_type
                    else 0,
                    "canonicalPath": chunk.canonical_path,
                    "itemIndex": chunk.item_index if chunk.item_index else 0,
                    "knowledgeScopeCode": scope_code,
                    "knowledgeScopeName": scope_name,
                    "businessCategory": business_category,
                    "documentTags": (document_tags or "").split(",") if document_tags else [],
                    "chunkText": chunk.content,
                }
            )

        if docs:
            resp = await es.bulk(operations=docs, refresh="wait_for")
            errors = [item for item in resp["items"] if "error" in item.get("index", {})]
            if errors:
                logger.warning("es index errors", count=len(errors))
            logger.info("es index done", count=len(child_chunks) - len(errors))
            return len(child_chunks) - len(errors)
        return 0

    async def index_nodes_to_neo4j(self, doc_id: str) -> int:
        """从 MySQL 读取解析好的层级节点，写入 Neo4j 构建图谱"""
        from app.config import get_settings

        if not get_settings().neo4j.enabled:
            logger.info("Neo4j is disabled, skipping graph injection")
            return 0

        from sqlalchemy import select

        from app.db.models.document import Document, DocumentStructureNode
        from app.db.session import get_session_factory
        from app.infra.neo4j import get_neo4j

        sf = get_session_factory()
        if sf is None:
            logger.warning("DB factory not initialized")
            return 0

        async with sf() as session:
            doc_stmt = select(Document.id).where(Document.doc_id == doc_id)
            doc_res = await session.execute(doc_stmt)
            doc_internal_id = doc_res.scalar_one_or_none()
            if doc_internal_id is None:
                logger.warning("Document not found for neo4j index", doc_id=doc_id)
                return 0
            stmt = (
                select(DocumentStructureNode)
                .where(DocumentStructureNode.document_id == doc_internal_id)
                .order_by(DocumentStructureNode.node_no)
            )
            res = await session.execute(stmt)
            nodes = res.scalars().all()

        if not nodes:
            logger.info("No structure nodes found for neo4j index", doc_id=doc_id)
            return 0

        driver = get_neo4j()

        # 1. 删除旧节点
        async with driver.session() as n_session:
            await n_session.run(
                "MATCH (n:DocumentNode {documentId: $doc_id}) DETACH DELETE n",
                doc_id=doc_internal_id,
            )

            # 2. 批量创建节点
            node_dicts = []
            for n in nodes:
                node_dicts.append(
                    {
                        "nodeId": n.id,
                        "documentId": n.document_id,
                        "nodeNo": n.node_no,
                        "nodeType": str(n.node_type) if n.node_type else "",
                        "parentNodeId": n.parent_node_id,
                        "title": n.title or "",
                        "depth": n.depth,
                        "content": n.content_text or "",
                    }
                )

            await n_session.run(
                """
                UNWIND $nodes AS n
                CREATE (node:DocumentNode {
                    nodeId: n.nodeId,
                    documentId: n.documentId,
                    nodeNo: n.nodeNo,
                    nodeType: n.nodeType,
                    parentNodeId: n.parentNodeId,
                    title: n.title,
                    depth: n.depth,
                    content: n.content
                })
                """,
                nodes=node_dicts,
            )

            # 3. 建立树形层级关系
            await n_session.run(
                """
                MATCH (child:DocumentNode {documentId: $doc_id})
                WHERE child.parentNodeId IS NOT NULL
                MATCH (parent:DocumentNode {nodeId: child.parentNodeId})
                MERGE (parent)-[:CONTAINS]->(child)
                """,
                doc_id=doc_internal_id,
            )

        logger.info("neo4j index done", doc_id=doc_id, nodes_count=len(nodes))
        return len(nodes)

    async def delete_doc(self, doc_id: str) -> None:
        """删除文档的所有 ES 索引和 Neo4j 图谱节点"""
        es = get_es()
        await es.delete_by_query(
            index=CHUNK_INDEX,
            body={"query": {"term": {"documentId": int(doc_id)}}},
        )

        from app.infra.neo4j import get_neo4j

        driver = get_neo4j()
        from sqlalchemy import select

        from app.db.models.document import Document
        from app.db.session import get_session_factory

        sf = get_session_factory()
        doc_internal_id = None
        if sf:
            async with sf() as session:
                doc_res = await session.execute(
                    select(Document.id).where(Document.doc_id == doc_id)
                )
                doc_internal_id = doc_res.scalar_one_or_none()

        if doc_internal_id:
            async with driver.session() as session:
                await session.run(
                    """
                    MATCH (n)
                    WHERE n.documentId = $doc_id
                    DETACH DELETE n
                    """,
                    doc_id=doc_internal_id,
                )

        logger.info("es and neo4j doc deleted", doc_id=doc_id)
