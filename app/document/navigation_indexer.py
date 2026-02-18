"""
ES Navigation Index 写入
将 DocumentStructureNode 同步到 ES 的 navigation_index 中，提供章节级的全文检索能力。
ES 导航索引服务。
"""

import structlog

from app.common.utils import safe_int
from app.db.models.document import DocumentStructureNode
from app.infra.es import get_es

logger = structlog.get_logger(__name__)

NAVIGATION_INDEX = "pipeline_rag_navigation_index"
DEFAULT_SEARCH_SIZE = 8
MAX_SEARCH_SIZE = 20
SECTION_NODE_TYPE = 0  # DocumentStructureNodeTypeEnum.SECTION


class NavigationIndexer:
    """文档大纲（Navigation）全文索引器"""

    async def index_nodes(
        self, doc_id: str, parse_task_id: str | None, nodes: list[DocumentStructureNode]
    ) -> int:
        """
        批量写入 Elasticsearch。
        """
        es = get_es()
        from typing import Any

        # 索引标题节点（node_type == 1 表示 Heading）和章节节点（node_type == 0）
        target_nodes = [
            n
            for n in nodes
            if n.node_type in (0, 1) and (n.content_text or n.title or n.section_path)
        ]
        if not target_nodes:
            return 0

        docs: list[dict[str, Any]] = []
        for node in target_nodes:
            docs.append({"index": {"_index": NAVIGATION_INDEX, "_id": str(node.id)}})
            docs.append(
                {
                    "nodeId": safe_int(node.id),
                    "documentId": safe_int(doc_id),
                    "parseTaskId": safe_int(parse_task_id),
                    "nodeType": str(node.node_type) if node.node_type is not None else "",
                    "nodeCode": node.node_code or "",
                    "nodeNo": node.node_no or 0,
                    "depth": node.depth or 0,
                    "parentNodeId": node.parent_node_id or 0,
                    "title": node.title or "",
                    "anchorText": node.anchor_text or "",
                    "sectionPath": node.section_path or "",
                    "canonicalPath": node.canonical_path or "",
                    "contentText": node.content_text or "",
                    "itemIndex": node.item_index or 0,
                }
            )

        if docs:
            resp = await es.bulk(operations=docs, refresh="wait_for")
            errors = [item for item in resp["items"] if "error" in item.get("index", {})]
            if errors:
                logger.warning("es navigation index errors", count=len(errors))
            logger.info(
                "es navigation index done", doc_id=doc_id, count=len(target_nodes) - len(errors)
            )
            return len(target_nodes) - len(errors)
        return 0

    async def delete_doc(self, doc_id: str) -> None:
        """删除该文档所有的 Navigation 索引"""
        es = get_es()
        await es.delete_by_query(
            index=NAVIGATION_INDEX,
            body={"query": {"term": {"documentId": int(doc_id)}}},
        )
        logger.info("es navigation doc deleted", doc_id=doc_id)

    async def search_sections(self, doc_id: str, query_text: str, top_k: int = 5) -> list[dict]:
        """
        全文本查询相关章节。
        模拟 ES 文档导航章节搜索
        加权：title^20, sectionPath^15, canonicalPath^5, contentText
        """
        es = get_es()
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"documentId": int(doc_id)}},
                        {
                            "multi_match": {
                                "query": query_text,
                                "fields": [
                                    "title^20",
                                    "sectionPath^15",
                                    "canonicalPath^5",
                                    "contentText",
                                ],
                            }
                        },
                    ]
                }
            },
            "size": top_k,
        }

        try:
            res = await es.search(index=NAVIGATION_INDEX, body=body)
            hits = res.get("hits", {}).get("hits", [])
            return [hit["_source"] for hit in hits]
        except Exception as e:
            logger.error(
                "es navigation search failed",
                error=str(e),
                doc_id=doc_id,
                query=query_text,
                exc_info=True,
            )
            return []


