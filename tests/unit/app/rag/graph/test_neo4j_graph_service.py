import types

import pytest

import app.rag.graph.neo4j_graph_service as neo4j_module
from app.rag.graph.neo4j_graph_service import (
    Neo4jGraphService,
    _as_int,
    _as_text,
    _neo_node_to_item,
    _neo_node_to_section,
    _normalize,
    _to_dict,
)


class FakeResult:
    def __init__(self, single=None, data=None):
        self._single = single
        self._data = data if data is not None else []

    async def single(self):
        return self._single

    async def data(self):
        return self._data


class FakeDriver:
    def __init__(self, error=None):
        self.error = error
        self.runs = []
        self.handler = None

    def session(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def run(self, query, **params):
        self.runs.append((query, params))
        if self.error:
            raise self.error
        if self.handler:
            return self.handler(query, params)
        return FakeResult()


@pytest.fixture
def fake_neo4j(monkeypatch):
    holder = {"driver": FakeDriver()}

    def install(error=None, handler=None):
        holder["driver"] = FakeDriver(error=error)
        holder["driver"].handler = handler
        monkeypatch.setattr(neo4j_module, "get_neo4j", lambda: holder["driver"])
        return holder["driver"]

    return install


def section_node(node_id=1, **overrides):
    d = {
        "nodeId": node_id,
        "documentId": 5,
        "nodeNo": 2,
        "depth": 1,
        "parentNodeId": 0,
        "nodeCode": "1.1",
        "title": "标题",
        "sectionPath": "1.1 标题",
        "contentText": "正文",
    }
    d.update(overrides)
    return d


def item_node(node_id=10, **overrides):
    d = {
        "nodeId": node_id,
        "documentId": 5,
        "nodeNo": 1,
        "nodeType": "STEP",
        "sectionNodeId": 2,
        "title": "步骤",
        "itemIndex": 1,
    }
    d.update(overrides)
    return d


def single(record):
    def handler(query, params):
        return FakeResult(single=record)

    return handler


def data(records):
    def handler(query, params):
        return FakeResult(data=records)

    return handler


class TestHelpers:
    def test_to_dict_dict(self):
        assert _to_dict({"a": 1}) == {"a": 1}

    def test_to_dict_items(self):
        assert _to_dict(types.SimpleNamespace(items=lambda: [("a", 1)])) == {"a": 1}

    def test_to_dict_unknown(self):
        assert _to_dict(object()) == {}

    def test_normalize(self):
        assert _normalize(" 安装 步骤  ") == "安装步骤"
        assert _normalize(">配置*手册#_") == "配置手册"
        assert _normalize(None) == ""

    def test_as_text(self):
        assert _as_text({"k": "  x  "}, "k") == "x"
        assert _as_text({"k": None}, "k") == ""
        assert _as_text({}, "k") == ""

    def test_as_int(self):
        assert _as_int({"k": "3"}, "k") == 3
        assert _as_int({"k": None}, "k") is None
        assert _as_int({}, "k") is None


class TestNeoNodeToSection:
    def test_camel_case(self):
        s = _neo_node_to_section(section_node(node_id=9))
        assert s["node_id"] == 9
        assert s["document_id"] == 5
        assert s["node_no"] == 2
        assert s["depth"] == 1
        assert s["node_code"] == "1.1"
        assert s["section_path"] == "1.1 标题"
        assert s["content_text"] == "正文"

    def test_snake_case_fallback(self):
        s = _neo_node_to_section({"node_id": 9, "document_id": 5, "title": "t"})
        assert s["node_id"] == 9
        assert s["document_id"] == 5

    def test_id_fallback(self):
        s = _neo_node_to_section({"id": 3, "doc_id": 7})
        assert s["node_id"] == 3
        assert s["document_id"] == 7

    def test_text_fields_stripped(self):
        s = _neo_node_to_section({"nodeId": 1, "documentId": 2, "title": "  x  "})
        assert s["title"] == "x"


class TestNeoNodeToItem:
    def test_mapping(self):
        i = _neo_node_to_item(item_node(node_id=11, nodeType="LIST_ITEM"))
        assert i["node_id"] == 11
        assert i["node_type"] == "LIST_ITEM"
        assert i["section_node_id"] == 2
        assert i["item_index"] == 1

    def test_snake_case_fallback(self):
        i = _neo_node_to_item({"node_id": 1, "document_id": 2, "node_type": "STEP"})
        assert i["node_type"] == "STEP"


class TestRunQuery:
    @pytest.mark.asyncio
    async def test_single_mode(self, fake_neo4j):
        driver = fake_neo4j(handler=single({"ok": True}))
        out = await Neo4jGraphService()._run_query("MATCH", {}, "t", "single")
        assert out == {"ok": True}
        assert "MATCH" in driver.runs[0][0]

    @pytest.mark.asyncio
    async def test_single_no_record_false(self, fake_neo4j):
        fake_neo4j()
        out = await Neo4jGraphService()._run_query("MATCH", {}, "t", "single")
        assert out is False

    @pytest.mark.asyncio
    async def test_data_mode(self, fake_neo4j):
        fake_neo4j(handler=data([{"a": 1}]))
        out = await Neo4jGraphService()._run_query("MATCH", {}, "t", "data")
        assert out == [{"a": 1}]

    @pytest.mark.asyncio
    async def test_unknown_mode(self, fake_neo4j):
        fake_neo4j()
        out = await Neo4jGraphService()._run_query("MATCH", {}, "t", "weird")
        assert out is False

    @pytest.mark.asyncio
    async def test_error_single_mode_false(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService()._run_query("MATCH", {}, "t", "single") is False

    @pytest.mark.asyncio
    async def test_error_data_mode_empty(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService()._run_query("MATCH", {}, "t", "data") == []


class TestIsGraphAvailable:
    @pytest.mark.asyncio
    async def test_available(self, fake_neo4j):
        fake_neo4j(handler=single({"available": True}))
        assert await Neo4jGraphService().is_graph_available("5") is True

    @pytest.mark.asyncio
    async def test_unavailable(self, fake_neo4j):
        fake_neo4j(handler=single({"available": False}))
        assert await Neo4jGraphService().is_graph_available("5") is False

    @pytest.mark.asyncio
    async def test_no_record(self, fake_neo4j):
        fake_neo4j()
        assert await Neo4jGraphService().is_graph_available("5") is False


class TestFindSectionBy:
    @pytest.mark.asyncio
    async def test_find_by_id(self, fake_neo4j):
        fake_neo4j(handler=single({"s": section_node(node_id=9)}))
        sec = await Neo4jGraphService().find_section_by_id("5", "9")
        assert sec.node_id == 9
        assert sec.document_id == 5

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, fake_neo4j):
        fake_neo4j()
        assert await Neo4jGraphService().find_section_by_id("5", "9") is None

    @pytest.mark.asyncio
    async def test_find_by_code_strips(self, fake_neo4j):
        driver = fake_neo4j(handler=single({"s": section_node()}))
        await Neo4jGraphService().find_section_by_code("5", " 1.1 ")
        assert driver.runs[0][1]["nodeCode"] == "1.1"

    @pytest.mark.asyncio
    async def test_find_by_title_normalizes(self, fake_neo4j):
        driver = fake_neo4j(handler=single({"s": section_node()}))
        await Neo4jGraphService().find_section_by_title("5", " 安装 指南 ")
        assert driver.runs[0][1]["normalized"] == "安装指南"

    @pytest.mark.asyncio
    async def test_find_by_canonical_path_strips(self, fake_neo4j):
        driver = fake_neo4j(handler=single({"s": section_node()}))
        await Neo4jGraphService().find_section_by_canonical_path("5", " /1.1 ")
        assert driver.runs[0][1]["canonicalPath"] == "/1.1"


class TestListSections:
    @pytest.mark.asyncio
    async def test_data(self, fake_neo4j):
        fake_neo4j(handler=data([{"s": section_node(node_id=1)}, {"s": section_node(node_id=2)}]))
        out = await Neo4jGraphService().list_sections("5")
        assert [s.node_id for s in out] == [1, 2]

    @pytest.mark.asyncio
    async def test_empty(self, fake_neo4j):
        fake_neo4j()
        assert await Neo4jGraphService().list_sections("5") == []


class TestGetDocumentTree:
    @pytest.mark.asyncio
    async def test_builds_result(self, fake_neo4j):
        fake_neo4j(
            handler=single(
                {"d": {"documentId": 5, "title": "手册"}, "sections": [section_node(node_id=1)]}
            )
        )
        out = await Neo4jGraphService().get_document_tree("5")
        assert out.doc == {"documentId": 5, "title": "手册"}
        assert [s.node_id for s in out.sections] == [1]

    @pytest.mark.asyncio
    async def test_no_record(self, fake_neo4j):
        fake_neo4j()
        assert await Neo4jGraphService().get_document_tree("5") is None

    @pytest.mark.asyncio
    async def test_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().get_document_tree("5") is None


class TestFindBestSection:
    @pytest.mark.asyncio
    async def test_title_beats_content(self, fake_neo4j):
        fake_neo4j(
            handler=data(
                [
                    {"s": section_node(node_id=1, title="其他", contentText="安装 相关")},
                    {"s": section_node(node_id=2, title="安装手册", contentText="x")},
                ]
            )
        )
        sec = await Neo4jGraphService().find_best_section("5", "安装", "")
        assert sec.node_id == 2

    @pytest.mark.asyncio
    async def test_facet_boost(self, fake_neo4j):
        fake_neo4j(
            handler=data(
                [
                    {"s": section_node(node_id=1, title="安装手册")},
                    {"s": section_node(node_id=2, title="安装", contentText="含 配置 内容")},
                ]
            )
        )
        sec = await Neo4jGraphService().find_best_section("5", "安装", "配置")
        assert sec.node_id == 2

    @pytest.mark.asyncio
    async def test_no_match(self, fake_neo4j):
        fake_neo4j(handler=data([{"s": section_node(node_id=1, title="别的")}]))
        assert await Neo4jGraphService().find_best_section("5", "不匹配", "") is None

    @pytest.mark.asyncio
    async def test_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().find_best_section("5", "安装", "") is None


class TestListChildren:
    @pytest.mark.asyncio
    async def test_data(self, fake_neo4j):
        fake_neo4j(handler=data([{"c": section_node(node_id=3)}]))
        out = await Neo4jGraphService().list_children("5", "2")
        assert [s.node_id for s in out] == [3]

    @pytest.mark.asyncio
    async def test_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().list_children("5", "2") == []


class TestParentSiblings:
    @pytest.mark.asyncio
    async def test_parent(self, fake_neo4j):
        fake_neo4j(handler=single({"p": section_node(node_id=1)}))
        sec = await Neo4jGraphService().parent_section("5", "2")
        assert sec.node_id == 1

    @pytest.mark.asyncio
    async def test_parent_not_found(self, fake_neo4j):
        fake_neo4j()
        assert await Neo4jGraphService().parent_section("5", "2") is None

    @pytest.mark.asyncio
    async def test_parent_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().parent_section("5", "2") is None

    @pytest.mark.asyncio
    async def test_previous_sibling(self, fake_neo4j):
        fake_neo4j(handler=single({"p": section_node(node_id=3)}))
        sec = await Neo4jGraphService().previous_sibling("5", "2")
        assert sec.node_id == 3

    @pytest.mark.asyncio
    async def test_next_sibling(self, fake_neo4j):
        fake_neo4j(handler=single({"n": section_node(node_id=4)}))
        sec = await Neo4jGraphService().next_sibling("5", "2")
        assert sec.node_id == 4


class TestItems:
    @pytest.mark.asyncio
    async def test_find_item_by_index(self, fake_neo4j):
        fake_neo4j(handler=single({"i": item_node(node_id=11)}))
        item = await Neo4jGraphService().find_item_by_index("5", "2", 1)
        assert item.node_id == 11
        assert item.item_index == 1

    @pytest.mark.asyncio
    async def test_find_item_not_found(self, fake_neo4j):
        fake_neo4j()
        assert await Neo4jGraphService().find_item_by_index("5", "2", 1) is None

    @pytest.mark.asyncio
    async def test_find_item_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().find_item_by_index("5", "2", 1) is None

    @pytest.mark.asyncio
    async def test_list_items(self, fake_neo4j):
        fake_neo4j(handler=data([{"i": item_node(node_id=11)}, {"i": item_node(node_id=12)}]))
        out = await Neo4jGraphService().list_items("5", "2")
        assert [i.node_id for i in out] == [11, 12]

    @pytest.mark.asyncio
    async def test_list_items_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().list_items("5", "2") == []

    @pytest.mark.asyncio
    async def test_search_items_normalizes_keyword(self, fake_neo4j):
        driver = fake_neo4j(handler=data([{"i": item_node()}]))
        out = await Neo4jGraphService().search_items_in_section("5", "2", " 步骤 ")
        assert len(out) == 1
        assert driver.runs[0][1]["keyword"] == "步骤"

    @pytest.mark.asyncio
    async def test_search_items_error(self, fake_neo4j):
        fake_neo4j(error=RuntimeError("down"))
        assert await Neo4jGraphService().search_items_in_section("5", "2", "k") == []
