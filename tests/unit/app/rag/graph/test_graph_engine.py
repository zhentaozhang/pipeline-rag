
import pytest

from app.rag.graph.graph_engine import StructureGraphQueryEngine
from app.rag.graph.models import GraphItem, GraphSection


class FakeGraphService:
    def __init__(self):
        self.calls = []
        self.section_by_id = {}
        self.best_section = None
        self.children = {}
        self.parents = {}
        self.prevs = {}
        self.nexts = {}
        self.item_by_index = {}
        self.items = {}
        self.search = {}
        self.by_title = {}

    async def find_section_by_id(self, doc_id, section_node_id):
        self.calls.append(("find_section_by_id", doc_id, section_node_id))
        return self.section_by_id.get(section_node_id)

    async def find_best_section(self, doc_id, topic, facet):
        self.calls.append(("find_best_section", doc_id, topic, facet))
        return self.best_section

    async def list_children(self, doc_id, section_node_id):
        self.calls.append(("list_children", doc_id, section_node_id))
        return self.children.get(section_node_id, [])

    async def parent_section(self, doc_id, section_node_id):
        self.calls.append(("parent_section", doc_id, section_node_id))
        return self.parents.get(section_node_id)

    async def previous_sibling(self, doc_id, section_node_id):
        self.calls.append(("previous_sibling", doc_id, section_node_id))
        return self.prevs.get(section_node_id)

    async def next_sibling(self, doc_id, section_node_id):
        self.calls.append(("next_sibling", doc_id, section_node_id))
        return self.nexts.get(section_node_id)

    async def find_item_by_index(self, doc_id, section_node_id, item_index):
        self.calls.append(("find_item_by_index", doc_id, section_node_id, item_index))
        return self.item_by_index.get((section_node_id, item_index))

    async def list_items(self, doc_id, section_node_id):
        self.calls.append(("list_items", doc_id, section_node_id))
        return self.items.get(section_node_id, [])

    async def search_items_in_section(self, doc_id, section_node_id, keyword):
        self.calls.append(("search_items_in_section", doc_id, section_node_id, keyword))
        return self.search.get((section_node_id, keyword), [])

    async def find_section_by_title(self, doc_id, title):
        self.calls.append(("find_section_by_title", doc_id, title))
        return self.by_title.get(title)


def make_section(node_id=1, **overrides):
    defaults = dict(node_id=node_id, document_id=5, title=f"标题{node_id}", section_path=f"{node_id}.x")
    defaults.update(overrides)
    return GraphSection(**defaults)


def make_item(node_id=100, section_node_id=1, node_no=1, **overrides):
    defaults = dict(
        node_id=node_id,
        document_id=5,
        section_node_id=section_node_id,
        node_no=node_no,
        title="条目",
    )
    defaults.update(overrides)
    return GraphItem(**defaults)


@pytest.fixture
def engine():
    eng = StructureGraphQueryEngine()
    eng.graph_service = FakeGraphService()
    return eng


class TestFindSectionWithChildren:
    @pytest.mark.asyncio
    async def test_int_node_id_uses_find_by_id(self, engine):
        sec = make_section(node_id=7)
        engine.graph_service.section_by_id = {"7": sec}
        engine.graph_service.children = {"7": [make_section(node_id=8)]}
        out = await engine.find_section_with_children("doc1", 7)
        assert engine.graph_service.calls[0][0] == "find_section_by_id"
        assert out.section.node_id == 7
        assert [c.node_id for c in out.children] == [8]

    @pytest.mark.asyncio
    async def test_digit_string_uses_find_by_id(self, engine):
        engine.graph_service.section_by_id = {"9": make_section(node_id=9)}
        engine.graph_service.children = {"9": []}
        out = await engine.find_section_with_children("doc1", "9")
        assert engine.graph_service.calls[0] == ("find_section_by_id", "doc1", "9")
        assert out.section.node_id == 9

    @pytest.mark.asyncio
    async def test_topic_uses_best_section(self, engine):
        engine.graph_service.best_section = make_section(node_id=3)
        engine.graph_service.children = {"3": []}
        out = await engine.find_section_with_children("doc1", "安装")
        assert engine.graph_service.calls[0] == ("find_best_section", "doc1", "安装", "")
        assert out.section.node_id == 3

    @pytest.mark.asyncio
    async def test_missing_section_returns_none(self, engine):
        out = await engine.find_section_with_children("doc1", "不存在的")
        assert out.section is None
        assert out.children == []


class TestFindSectionWithSiblings:
    @pytest.mark.asyncio
    async def test_missing_section_short_circuit(self, engine):
        out = await engine.find_section_with_siblings("doc1", "1")
        assert out.section is None
        assert out.parent is None

    @pytest.mark.asyncio
    async def test_full_assembly(self, engine):
        sec = make_section(node_id=2)
        parent = make_section(node_id=1)
        prev = make_section(node_id=3)
        nxt = make_section(node_id=4)
        engine.graph_service.section_by_id = {"2": sec}
        engine.graph_service.parents = {"2": parent}
        engine.graph_service.prevs = {"2": prev}
        engine.graph_service.nexts = {"2": nxt}
        out = await engine.find_section_with_siblings("doc1", "2")
        assert out.section is sec
        assert out.parent is parent
        assert out.previous_sibling is prev
        assert out.next_sibling is nxt

    @pytest.mark.asyncio
    async def test_partial_siblings(self, engine):
        sec = make_section(node_id=2)
        engine.graph_service.section_by_id = {"2": sec}
        out = await engine.find_section_with_siblings("doc1", "2")
        assert out.parent is None
        assert out.previous_sibling is None
        assert out.next_sibling is None


class TestSearchItemsInSection:
    @pytest.mark.asyncio
    async def test_delegates_with_keyword(self, engine):
        item = make_item(node_id=1)
        engine.graph_service.search = {("2", "安装"): [item]}
        out = await engine.search_items_in_section("doc1", "2", "安装")
        assert out == [item]
        assert engine.graph_service.calls[0] == ("search_items_in_section", "doc1", "2", "安装")

    @pytest.mark.asyncio
    async def test_none_keyword_becomes_empty_string(self, engine):
        await engine.search_items_in_section("doc1", "2", None)
        assert engine.graph_service.calls[0] == ("search_items_in_section", "doc1", "2", "")


class TestFindItemInSectionTree:
    @pytest.mark.asyncio
    async def test_none_guard(self, engine):
        assert await engine._find_item_in_section_tree(None, "2", 1) is None
        assert await engine._find_item_in_section_tree("doc1", None, 1) is None
        assert await engine._find_item_in_section_tree("doc1", "2", None) is None

    @pytest.mark.asyncio
    async def test_found_in_current(self, engine):
        item = make_item(node_id=5)
        engine.graph_service.item_by_index = {("2", 1): item}
        out = await engine._find_item_in_section_tree("doc1", "2", 1)
        assert out is item

    @pytest.mark.asyncio
    async def test_found_in_descendant(self, engine):
        child = make_section(node_id=3)
        engine.graph_service.children = {"2": [child, make_section(node_id=4)]}
        item = make_item(node_id=5, section_node_id=3)
        engine.graph_service.item_by_index = {("3", 1): item}
        out = await engine._find_item_in_section_tree("doc1", "2", 1)
        assert out is item

    @pytest.mark.asyncio
    async def test_not_found(self, engine):
        engine.graph_service.children = {"2": [make_section(node_id=3)]}
        assert await engine._find_item_in_section_tree("doc1", "2", 99) is None


class TestListItemsInSectionTree:
    @pytest.mark.asyncio
    async def test_none_guard(self, engine):
        assert await engine._list_items_in_section_tree(None, "2") == []
        assert await engine._list_items_in_section_tree("doc1", None) == []

    @pytest.mark.asyncio
    async def test_recursive_merge_sorted(self, engine):
        child = make_section(node_id=3)
        engine.graph_service.items = {
            "2": [make_item(node_id=1, section_node_id=2, node_no=3)],
            "3": [make_item(node_id=2, section_node_id=3, node_no=1)],
        }
        engine.graph_service.children = {"2": [child]}
        out = await engine._list_items_in_section_tree("doc1", "2")
        assert [i.node_id for i in out] == [2, 1]

    @pytest.mark.asyncio
    async def test_missing_node_no_sorted_last(self, engine):
        engine.graph_service.items = {
            "2": [
                make_item(node_id=1, node_no=None),
                make_item(node_id=2, node_no=1),
            ]
        }
        engine.graph_service.children = {"2": []}
        out = await engine._list_items_in_section_tree("doc1", "2")
        assert [i.node_id for i in out] == [2, 1]


class TestSearchItemsInSectionTree:
    @pytest.mark.asyncio
    async def test_none_guard(self, engine):
        assert await engine._search_items_in_section_tree(None, "2", "k") == []
        assert await engine._search_items_in_section_tree("doc1", None, "k") == []

    @pytest.mark.asyncio
    async def test_recursive_dedup_sorted(self, engine):
        child = make_section(node_id=3)
        dup = make_item(node_id=9, node_no=2)
        engine.graph_service.search = {
            ("2", "k"): [make_item(node_id=1, node_no=4), dup],
            ("3", "k"): [dup, make_item(node_id=3, node_no=1)],
        }
        engine.graph_service.children = {"2": [child]}
        out = await engine._search_items_in_section_tree("doc1", "2", "k")
        assert [i.node_id for i in out] == [3, 9, 1]


class TestBuildGraphResult:
    @pytest.mark.asyncio
    async def test_no_target_section_returns_empty(self, engine):
        out = await engine.build_graph_result("doc1", target_section_node_id=None)
        assert out.target_section is None
        assert out.doc == {}

    @pytest.mark.asyncio
    async def test_section_not_found_returns_empty(self, engine):
        out = await engine.build_graph_result("doc1", target_section_node_id="99")
        assert out.target_section is None

    @pytest.mark.asyncio
    async def test_full_build_with_target_item(self, engine):
        sec = make_section(node_id=2)
        child = make_section(node_id=3)
        item = make_item(node_id=10, section_node_id=2, node_no=1)
        owner = make_section(node_id=2)
        engine.graph_service.section_by_id = {"2": sec, "3": owner}
        engine.graph_service.children = {"2": [child]}
        engine.graph_service.items = {"2": [item]}
        engine.graph_service.item_by_index = {("2", 1): item}
        engine.graph_service.parents = {"2": make_section(node_id=1)}
        out = await engine.build_graph_result("doc1", target_section_node_id="2", target_item_index=1)
        assert out.target_section.node_id == 2
        assert out.target_item is item
        assert [c.node_id for c in out.children] == [3]
        assert out.all_items == [item]
        assert out.parent_section.node_id == 1

    @pytest.mark.asyncio
    async def test_matched_single_item_promoted(self, engine):
        sec = make_section(node_id=2)
        item = make_item(node_id=10, section_node_id=3, node_no=1)
        owner = make_section(node_id=3)
        engine.graph_service.section_by_id = {"2": sec, "3": owner}
        engine.graph_service.children = {"2": []}
        engine.graph_service.search = {("2", "安装"): [item]}
        out = await engine.build_graph_result("doc1", target_section_node_id="2", item_keyword="安装")
        assert out.target_section.node_id == 3
        assert out.target_item is item
        assert out.matched_items == [item]

    @pytest.mark.asyncio
    async def test_blank_keyword_no_match(self, engine):
        sec = make_section(node_id=2)
        engine.graph_service.section_by_id = {"2": sec}
        engine.graph_service.children = {"2": []}
        out = await engine.build_graph_result("doc1", target_section_node_id="2", item_keyword="  ")
        assert out.matched_items == []


class TestFindSectionByTitle:
    @pytest.mark.asyncio
    async def test_proxy(self, engine):
        sec = make_section(node_id=5)
        engine.graph_service.by_title = {"安装": sec}
        out = await engine.find_section_by_title("doc1", "安装")
        assert out is sec
        assert engine.graph_service.calls[0] == ("find_section_by_title", "doc1", "安装")
