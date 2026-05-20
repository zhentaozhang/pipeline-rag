"""
图谱查询结果渲染器

功能：
- renderGraphAnswer: 顶层路由（GRAPH_THEN_EVIDENCE vs GRAPH_ONLY）
- renderAdjacency: 相邻章节渲染
- renderChildren: 子章节列表渲染
- renderGraphThenEvidence: item 命中 + section 内容回退
- formatItem: 编号项格式化
"""

from app.rag.graph.models import GraphItem, GraphQueryResult, GraphSection


class GraphAnswerRenderer:
    """
    将 Neo4j 返回的结构化 JSON 数据，渲染为自然语言文本。
    """

    def render_graph_answer(
        self,
        mode: str,
        graph_result: GraphQueryResult | None,
        question: str = "",
        navigation_action: str | None = None,
    ) -> str:
        if not graph_result or not graph_result.target_section:
            return ""

        if mode == "GRAPH_THEN_EVIDENCE":
            return self._render_graph_then_evidence(graph_result)
        return self._render_graph_only(graph_result, question, navigation_action)

    def _render_graph_only(
        self,
        graph_result: GraphQueryResult,
        question: str = "",
        navigation_action: str | None = None,
    ) -> str:
        target = graph_result.target_section
        if target is None:
            return ""
        if navigation_action == "SECTION_ADJACENCY_LOOKUP" or self._asks_adjacency(question):
            return self.render_adjacency(
                target,
                graph_result.prev_sibling,
                graph_result.next_sibling,
                graph_result.parent_section,
            )
        if self._asks_children(question) or bool(graph_result.children):
            return self.render_children(target, graph_result.children)
        return target.display_title()

    def _render_graph_then_evidence(self, graph_result: GraphQueryResult) -> str:
        """图+证据模式渲染。"""
        target = graph_result.target_section
        if target is None:
            return ""

        if graph_result.target_item:
            item = graph_result.target_item
            section_title = target.display_title()
            return f'"{section_title}"中的第{item.item_index}步是：\n{self._format_item(item)}'

        if graph_result.matched_items:
            lines = [f'在"{target.display_title()}"中命中了以下步骤：']
            for item in graph_result.matched_items:
                lines.append(self._format_item(item))
            return "\n".join(lines)

        if target.content_text and target.content_text.strip():
            return f'"{target.display_title()}"中的相关内容如下：\n{target.content_text.strip()}'
        return target.display_title()

    def render_adjacency(
        self,
        section: GraphSection,
        prev_sib: GraphSection | None = None,
        next_sib: GraphSection | None = None,
        parent: GraphSection | None = None,
    ) -> str:
        """相邻章节渲染。"""
        section_title = section.display_title()
        lines = [f'目标章节是："{section_title}"。']

        if parent:
            lines.append(f'它属于："{parent.display_title()}"。')

        lines.append(f"上一节：{self._format_section_or_fallback(prev_sib)}")
        lines.append(f"下一节：{self._format_section_or_fallback(next_sib)}")
        return "\n".join(lines)

    def render_children(self, section: GraphSection, children: list[GraphSection] | None) -> str:
        """子章节列表渲染。"""
        section_title = section.display_title()
        if not children:
            return f"\u201c{section_title}\u201d包含以下章节：\n未找到直接子章节。"
        lines = [f"\u201c{section_title}\u201d包含以下章节："]
        for child in children:
            lines.append(f"- {child.display_title()}")
        return "\n".join(lines)

    def _format_item(self, item: GraphItem | None) -> str:
        if not item:
            return ""
        if item.item_index is not None:
            display = item.content_text or item.title or ""
            return f"第{item.item_index}步：{display}"
        return item.content_text or item.title or ""

    def _format_section_or_fallback(self, section: GraphSection | None) -> str:
        return "未找到相邻章节" if not section else f'"{section.display_title()}"'

    # ── 问题检测 ──────────────────────────────────────────────────────────

    def _asks_adjacency(self, question: str) -> bool:
        return any(
            kw in question for kw in ["上一节", "下一节", "前一节", "后一节", "属于哪个章节"]
        )

    def _asks_children(self, question: str) -> bool:
        return any(
            kw in question for kw in ["包含哪些章节", "都包含哪些章节", "有哪些小节", "有哪些章节"]
        )

    @staticmethod
    def render_tree(tree_data: GraphQueryResult | None) -> str:
        if not tree_data:
            return "未找到相关的文档结构树信息。"
        doc = tree_data.doc
        sections = tree_data.sections
        title = doc.get("title", "未知文档")
        doc_id = doc.get("doc_id", "")
        lines = [f"【{title}】(ID: {doc_id}) 的结构如下："]
        for idx, s in enumerate(sections, 1):
            lines.append(f"{idx}. {s.title or '未命名章节'}")
        return "\n".join(lines)

    @staticmethod
    def render_path(path_data: list[GraphSection] | None) -> str:
        if not path_data:
            return "未找到相关联的路径节点。"
        lines = ["关联的章节节点有："]
        for p in path_data:
            lines.append(f" - {p.title or '未命名章节'}")
        return "\n".join(lines)
