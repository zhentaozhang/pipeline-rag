"""
复合图查询引擎 (CompositeGraphService)
对每个方法调用，先检查 Neo4j 是否可用，可用则使用 Neo4j，
否则降级到 MySQL。
"""

import structlog

from app.rag.graph.models import (
    GraphItem,
    GraphQueryResult,
    GraphSection,
)
from app.rag.graph.mysql_graph_service import MysqlGraphService
from app.rag.graph.neo4j_graph_service import Neo4jGraphService

logger = structlog.get_logger(__name__)


class CompositeGraphService:
    def __init__(self):
        self.neo4j_service = Neo4jGraphService()
        self.mysql_service = MysqlGraphService()

    async def _delegate(self, doc_id: str):
        """检查 Neo4j 是否可用，可用则返回图服务，否则降级到 MySQL。"""
        try:
            if await self.neo4j_service.is_graph_available(doc_id):
                logger.info("using neo4j for graph service", doc_id=doc_id)
                return self.neo4j_service
        except Exception as exc:
            logger.warning(
                "neo4j unavailable, falling back to mysql", error=str(exc), exc_info=True
            )
        logger.info("using mysql fallback for graph service", doc_id=doc_id)
        return self.mysql_service

    async def is_graph_available(self, doc_id: str) -> bool:
        return await self.neo4j_service.is_graph_available(doc_id)

    async def get_document_tree(self, doc_id: str) -> GraphQueryResult | None:
        svc = await self._delegate(doc_id)
        return await svc.get_document_tree(doc_id)

    async def find_section_by_id(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.find_section_by_id(doc_id, section_node_id)

    async def find_section_by_code(self, doc_id: str, node_code: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.find_section_by_code(doc_id, node_code)

    async def find_section_by_title(self, doc_id: str, title: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.find_section_by_title(doc_id, title)

    async def find_section_by_canonical_path(
        self, doc_id: str, canonical_path: str
    ) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.find_section_by_canonical_path(doc_id, canonical_path)

    async def find_best_section(self, doc_id: str, topic: str, facet: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.find_best_section(doc_id, topic, facet)

    async def list_sections(self, doc_id: str) -> list[GraphSection]:
        svc = await self._delegate(doc_id)
        return await svc.list_sections(doc_id)

    async def list_children(self, doc_id: str, section_node_id: str) -> list[GraphSection]:
        svc = await self._delegate(doc_id)
        return await svc.list_children(doc_id, section_node_id)

    async def parent_section(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.parent_section(doc_id, section_node_id)

    async def previous_sibling(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.previous_sibling(doc_id, section_node_id)

    async def next_sibling(self, doc_id: str, section_node_id: str) -> GraphSection | None:
        svc = await self._delegate(doc_id)
        return await svc.next_sibling(doc_id, section_node_id)

    async def find_item_by_index(
        self, doc_id: str, section_node_id: str, item_index: int
    ) -> GraphItem | None:
        svc = await self._delegate(doc_id)
        return await svc.find_item_by_index(doc_id, section_node_id, item_index)

    async def list_items(self, doc_id: str, section_node_id: str) -> list[GraphItem]:
        svc = await self._delegate(doc_id)
        return await svc.list_items(doc_id, section_node_id)

    async def search_items_in_section(
        self, doc_id: str, section_node_id: str, keyword: str
    ) -> list[GraphItem]:
        svc = await self._delegate(doc_id)
        return await svc.search_items_in_section(doc_id, section_node_id, keyword)
