from app.rag.graph.models import (
    GraphItem,
    GraphQueryResult,
    GraphSection,
    GraphSectionWithChildren,
    GraphSectionWithSiblings,
)


class TestGraphItem:
    def test_alias_populate(self):
        item = GraphItem(
            nodeId=1,
            documentId=2,
            parseTaskId=3,
            nodeNo=4,
            node_type="STEP",
            sectionNodeId=5,
            prevSiblingNodeId=6,
            nextSiblingNodeId=7,
            anchorText="锚",
            sectionPath="1.1",
            canonicalPath="/1.1",
            contentText="正文",
            itemIndex=2,
        )
        assert item.node_id == 1
        assert item.document_id == 2
        assert item.parse_task_id == 3
        assert item.node_no == 4
        assert item.node_type == "STEP"
        assert item.section_node_id == 5
        assert item.prev_sibling_node_id == 6
        assert item.next_sibling_node_id == 7
        assert item.anchor_text == "锚"
        assert item.section_path == "1.1"
        assert item.canonical_path == "/1.1"
        assert item.content_text == "正文"
        assert item.item_index == 2

    def test_populate_by_name(self):
        item = GraphItem(node_id=1, document_id=2)
        assert item.node_id == 1

    def test_defaults(self):
        item = GraphItem(nodeId=1, documentId=2)
        assert item.node_no is None
        assert item.node_type is None
        assert item.item_index is None

    def test_display_text_priority(self):
        item = GraphItem(nodeId=1, documentId=2, content_text="正文", anchor_text="锚", title="标题")
        assert item.display_text() == "正文"

    def test_display_text_fallback(self):
        assert GraphItem(nodeId=1, documentId=2, content_text=None, anchor_text="锚", title="标题").display_text() == "锚"
        assert GraphItem(nodeId=1, documentId=2, title="标题").display_text() == "标题"
        assert GraphItem(nodeId=1, documentId=2).display_text() == ""


class TestGraphSection:
    def test_alias_populate(self):
        section = GraphSection(
            nodeId=1, documentId=2, parentNodeId=3, nodeCode="1.1", title="标题", depth=2
        )
        assert section.node_id == 1
        assert section.document_id == 2
        assert section.parent_node_id == 3
        assert section.node_code == "1.1"
        assert section.depth == 2

    def test_display_title_section_path_priority(self):
        section = GraphSection(
            nodeId=1,
            documentId=2,
            section_path="1.1 安装",
            node_code="1.1",
            title="安装",
        )
        assert section.display_title() == "1.1 安装"

    def test_display_title_node_code_prefix(self):
        section = GraphSection(nodeId=1, documentId=2, node_code="2.3", title="配置")
        assert section.display_title() == "2.3 配置"

    def test_display_title_title_only(self):
        section = GraphSection(nodeId=1, documentId=2, title="配置")
        assert section.display_title() == "配置"

    def test_display_title_empty(self):
        assert GraphSection(nodeId=1, documentId=2).display_title() == ""


class TestWrappers:
    def test_with_siblings(self):
        sec = GraphSection(nodeId=1, documentId=2)
        sib = GraphSection(nodeId=3, documentId=2)
        w = GraphSectionWithSiblings(section=sec, previousSibling=sib)
        assert w.section is sec
        assert w.previous_sibling is sib
        assert w.next_sibling is None

    def test_with_children(self):
        child = GraphSection(nodeId=2, documentId=1)
        w = GraphSectionWithChildren(section=None, children=[child])
        assert w.section is None
        assert w.children == [child]

    def test_query_result_defaults(self):
        r = GraphQueryResult()
        assert r.doc == {}
        assert r.sections == []
        assert r.target_section is None
        assert r.children == []
        assert r.all_items == []
        assert r.matched_items == []

    def test_query_result_alias(self):
        item = GraphItem(nodeId=1, documentId=2)
        r = GraphQueryResult(targetSection=GraphSection(nodeId=9, documentId=2), targetItem=item, allItems=[item])
        assert r.target_section.node_id == 9
        assert r.target_item is item
        assert r.all_items == [item]
