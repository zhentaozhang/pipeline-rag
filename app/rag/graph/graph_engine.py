"""
文档结构图谱高级查询引擎
聚合底层 CompositeGraphService 提供复杂的树形操作，
如递归搜索、图结果构建、相邻章节查询等。
"""

import structlog

from app.common.utils import safe_int
from app.rag.graph.models import (
    GraphItem,
    GraphQueryResult,
    GraphSection,
    GraphSectionWithChildren,
    GraphSectionWithSiblings,
)

logger = structlog.get_logger(__name__)


class StructureGraphQueryEngine:
    """
    文档结构图谱高级查询引擎。
    """

    def __init__(self):
        from app.rag.graph.composite_graph_service import CompositeGraphService

        self.graph_service = CompositeGraphService()

    # ── Public API ─────────────────────────────────────────────────────────

    async def find_section_with_children(
        self, doc_id: str, topic_or_node_id: str | int
    ) -> GraphSectionWithChildren:
        """
        按主题名或节点 ID 查找章节及其子章节。
        """
        if isinstance(topic_or_node_id, int) or (
            isinstance(topic_or_node_id, str) and topic_or_node_id.isdigit()
        ):
            section_node_id = safe_int(topic_or_node_id)
            section = await self.graph_service.find_section_by_id(doc_id, str(section_node_id))
        else:
            section = await self.graph_service.find_best_section(doc_id, topic_or_node_id, "")

        if section is None:
            return GraphSectionWithChildren(section=None)

        children = await self.graph_service.list_children(doc_id, str(section.node_id))
        logger.info(
            "structure graph find children",
            doc_id=doc_id,
            section_node_id=section.node_id,
            target_section=section.display_title(),
            child_count=len(children),
        )
        return GraphSectionWithChildren(section=section, children=children)

    async def find_section_with_siblings(
        self, doc_id: str, section_node_id: str
    ) -> GraphSectionWithSiblings:
        """查找章节及其兄弟节点（上一章/下一章/父章节）。"""
        section = await self.graph_service.find_section_by_id(doc_id, section_node_id)
        if section is None:
            return GraphSectionWithSiblings(section=None)

        parent = await self.graph_service.parent_section(doc_id, section_node_id)
        prev_sib = await self.graph_service.previous_sibling(doc_id, section_node_id)
        next_sib = await self.graph_service.next_sibling(doc_id, section_node_id)

        logger.info(
            "structure graph find siblings",
            doc_id=doc_id,
            section_node_id=section_node_id,
            target_section=section.display_title(),
            parent=parent.display_title() if parent else "",
            previous=prev_sib.display_title() if prev_sib else "",
            next_=next_sib.display_title() if next_sib else "",
        )
        return GraphSectionWithSiblings(
            section=section,
            parent=parent,
            previous_sibling=prev_sib,
            next_sibling=next_sib,
        )

    async def search_items_in_section(
        self, doc_id: str, section_node_id: str, keyword: str
    ) -> list[GraphItem]:
        """在章节内搜索匹配关键字的条目。"""
        items = await self._search_items_in_section_tree(doc_id, section_node_id, keyword or "")
        logger.info(
            "structure graph search items in section",
            doc_id=doc_id,
            section_node_id=section_node_id,
            keyword=keyword or "",
            matched_count=len(items),
        )
        return items

    async def build_graph_result(
        self,
        doc_id: str,
        target_section_node_id: str | None = None,
        target_item_index: int | None = None,
        item_keyword: str | None = None,
    ) -> GraphQueryResult:
        """
        构建完整的 GraphQueryResult，包含目标 section、children、all items、
        target item、matched items、parent、siblings 等。
        """
        section: GraphSection | None = None
        if target_section_node_id:
            section = await self.graph_service.find_section_by_id(doc_id, target_section_node_id)

        if section is None:
            return GraphQueryResult()

        section_node_id_val = str(section.node_id)
        children = await self.graph_service.list_children(doc_id, section_node_id_val)
        all_items = await self._list_items_in_section_tree(doc_id, section_node_id_val)
        target_item = (
            await self._find_item_in_section_tree(doc_id, section_node_id_val, target_item_index)
            if target_item_index is not None
            else None
        )
        matched_items = (
            await self._search_items_in_section_tree(doc_id, section_node_id_val, item_keyword)
            if item_keyword and item_keyword.strip()
            else []
        )

        # resolve item owner section
        resolved_section = section
        if target_item is not None and target_item.section_node_id is not None:
            owner = await self.graph_service.find_section_by_id(
                doc_id, str(target_item.section_node_id)
            )
            if owner:
                resolved_section = owner
        elif len(matched_items) == 1 and matched_items[0].section_node_id is not None:
            owner = await self.graph_service.find_section_by_id(
                doc_id, str(matched_items[0].section_node_id)
            )
            if owner:
                resolved_section = owner
                target_item = matched_items[0]

        parent_section = None
        prev_sibling = None
        next_sibling = None
        if resolved_section:
            resolved_id = str(resolved_section.node_id)
            parent_section = await self.graph_service.parent_section(doc_id, resolved_id)
            prev_sibling = await self.graph_service.previous_sibling(doc_id, resolved_id)
            next_sibling = await self.graph_service.next_sibling(doc_id, resolved_id)

        result = GraphQueryResult(
            target_section=resolved_section,
            children=children,
            all_items=all_items,
            target_item=target_item,
            matched_items=matched_items,
            parent_section=parent_section,
            prev_sibling=prev_sibling,
            next_sibling=next_sibling,
        )

        logger.info(
            "structure graph result built",
            doc_id=doc_id,
            target_section_node_id=target_section_node_id,
            target_item_index=target_item_index,
            item_keyword=item_keyword or "",
            target_section=resolved_section.display_title() if resolved_section else "",
            target_item_found=target_item is not None and target_item.node_id != 0
            if target_item
            else False,
            child_count=len(children),
            all_item_count=len(all_items),
            matched_item_count=len(matched_items),
        )
        return result

    # ── 已有兼容方法 ───────────────────────────────────────────────────────

    async def find_section_by_title(self, doc_id: str, title: str) -> GraphSection | None:
        """根据标题或路径搜索章节节点（代理到 CompositeGraphService）"""
        return await self.graph_service.find_section_by_title(doc_id, title)

    # ── Private helpers ───────────────────────────────────────────────────

    async def _find_item_in_section_tree(
        self, doc_id: str, section_node_id: str, item_index: int
    ) -> GraphItem | None:
        """递归在当前 section 及其所有子 section 中寻找指定序号的 item"""
        if doc_id is None or section_node_id is None or item_index is None:
            return None

        item = await self.graph_service.find_item_by_index(doc_id, section_node_id, item_index)
        if item:
            return item

        children = await self.graph_service.list_children(doc_id, section_node_id)
        for child in children:
            descendant = await self._find_item_in_section_tree(
                doc_id, str(child.node_id), item_index
            )
            if descendant:
                return descendant
        return None

    async def _list_items_in_section_tree(
        self, doc_id: str, section_node_id: str
    ) -> list[GraphItem]:
        """递归列出当前 section 及其子 section 下的所有 items，按 node_no 排序"""
        if doc_id is None or section_node_id is None:
            return []

        items = list(await self.graph_service.list_items(doc_id, section_node_id))
        children = await self.graph_service.list_children(doc_id, section_node_id)
        for child in children:
            items.extend(await self._list_items_in_section_tree(doc_id, str(child.node_id)))

        items.sort(
            key=lambda i: i.node_no if i.node_no is not None else float("inf"),
        )
        return items

    async def _search_items_in_section_tree(
        self, doc_id: str, section_node_id: str, keyword: str
    ) -> list[GraphItem]:
        """递归搜索当前 section 及其子 section 下匹配 keyword 的 items"""
        if doc_id is None or section_node_id is None:
            return []

        items = list(
            await self.graph_service.search_items_in_section(doc_id, section_node_id, keyword)
        )
        children = await self.graph_service.list_children(doc_id, section_node_id)
        for child in children:
            items.extend(
                await self._search_items_in_section_tree(doc_id, str(child.node_id), keyword)
            )

        seen = set()
        unique_items = []
        for item in items:
            if item.node_id not in seen:
                seen.add(item.node_id)
                unique_items.append(item)
        unique_items.sort(
            key=lambda i: i.node_no if i.node_no is not None else float("inf"),
        )
        return unique_items
