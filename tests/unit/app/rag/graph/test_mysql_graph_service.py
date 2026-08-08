import types

import pytest

from app.db.models.document import DocumentStructureNode
from app.rag.graph.mysql_graph_service import (
    MysqlGraphService,
    _normalize,
    _safe_text,
)


def make_node(node_id=1, **overrides):
    defaults = dict(
        id=node_id,
        document_id=5,
        parse_task_id=None,
        node_no=1,
        node_type=2,
        parent_node_id=None,
        prev_sibling_node_id=None,
        next_sibling_node_id=None,
        depth=1,
        node_code=None,
        title="标题",
        anchor_text=None,
        canonical_path="/标题",
        section_path="标题",
        content_text=None,
        item_index=None,
    )
    defaults.update(overrides)
    return DocumentStructureNode(**defaults)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return types.SimpleNamespace(all=lambda: [r for r in self.rows if r is not None])

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, queue):
        self.queue = list(queue)
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt):
        self.executed.append(str(stmt))
        if not self.queue:
            raise AssertionError("no more queued results for execute")
        return self.queue.pop(0)


@pytest.fixture
def fake_db(monkeypatch):
    holder = {"queue": [], "session": None}

    def install(queue):
        holder["queue"] = list(queue)
        holder["session"] = FakeSession(holder["queue"])
        monkeypatch.setattr(
            "app.rag.graph.mysql_graph_service.async_session_maker",
            lambda: holder["session"],
        )
        return holder["session"]

    return install


class TestNormalize:
    def test_strips_whitespace_and_symbols(self):
        assert _normalize(" 安装 步骤  ") == "安装步骤"
        assert _normalize(">配置*手册#_") == "配置手册"
        assert _normalize("a#b*c-d_e") == "abcde"

    def test_empty_input(self):
        assert _normalize(None) == ""
        assert _normalize("") == ""
        assert _normalize("   ") == ""

    def test_lowercase(self):
        assert _normalize("ABC") == "abc"


class TestSafeText:
    def test_strips(self):
        assert _safe_text("  hello  ") == "hello"

    def test_empty(self):
        assert _safe_text(None) == ""
        assert _safe_text("") == ""


class TestToSection:
    def test_maps_fields(self):
        node = make_node(
            node_id=9,
            node_no=3,
            node_type=2,
            depth=2,
            parent_node_id=1,
            prev_sibling_node_id=2,
            next_sibling_node_id=3,
            node_code="1.1",
            title=" 标题 ",
            anchor_text=" 锚 ",
            section_path=" 1.1 标题 ",
            canonical_path=" /1.1 ",
            content_text=" 正文 ",
        )
        sec = MysqlGraphService()._to_section(node)
        assert sec.node_id == 9
        assert sec.document_id == 5
        assert sec.depth == 2
        assert sec.parent_node_id == 1
        assert sec.node_code == "1.1"
        assert sec.title == "标题"
        assert sec.anchor_text == "锚"
        assert sec.section_path == "1.1 标题"
        assert sec.canonical_path == "/1.1"
        assert sec.content_text == "正文"

    def test_none_text_becomes_empty(self):
        sec = MysqlGraphService()._to_section(make_node())
        assert sec.node_code == ""


class TestToItem:
    def test_node_type_mapping(self):
        step = MysqlGraphService()._to_item(make_node(node_type=3, parent_node_id=7, item_index=2))
        assert step.node_type == "STEP"
        assert step.section_node_id == 7
        assert step.item_index == 2
        li = MysqlGraphService()._to_item(make_node(node_type=4))
        assert li.node_type == "LIST_ITEM"

    def test_unknown_node_type(self):
        item = MysqlGraphService()._to_item(make_node(node_type=9))
        assert item.node_type == ""


class TestGetDocumentTree:
    @pytest.mark.asyncio
    async def test_no_nodes_returns_none(self, fake_db):
        fake_db([FakeResult([])])
        assert await MysqlGraphService().get_document_tree("doc1") is None

    @pytest.mark.asyncio
    async def test_builds_result(self, fake_db):
        fake_db([FakeResult([make_node(node_id=1), make_node(node_id=2)])])
        out = await MysqlGraphService().get_document_tree("doc1")
        assert out.doc == {"doc_id": "doc1"}
        assert [s.node_id for s in out.sections] == [1, 2]


class TestFindSectionById:
    @pytest.mark.asyncio
    async def test_found(self, fake_db):
        fake_db([FakeResult([make_node(node_id=9)])])
        sec = await MysqlGraphService().find_section_by_id("doc1", "9")
        assert sec.node_id == 9

    @pytest.mark.asyncio
    async def test_not_found(self, fake_db):
        fake_db([FakeResult([])])
        assert await MysqlGraphService().find_section_by_id("doc1", "9") is None


class TestFindSectionByCode:
    @pytest.mark.asyncio
    async def test_found_strips_code(self, fake_db):
        fake_db([FakeResult([make_node(node_id=9)])])
        sec = await MysqlGraphService().find_section_by_code("doc1", " 1.1 ")
        assert sec.node_id == 9

    @pytest.mark.asyncio
    async def test_not_found(self, fake_db):
        fake_db([FakeResult([])])
        assert await MysqlGraphService().find_section_by_code("doc1", "9") is None


class TestFindSectionByTitle:
    @pytest.mark.asyncio
    async def test_matches_title_normalized(self, fake_db):
        fake_db([FakeResult([make_node(node_id=1, title=" 安装 指南 ", section_path="x")])])
        sec = await MysqlGraphService().find_section_by_title("doc1", "安装指南")
        assert sec.node_id == 1

    @pytest.mark.asyncio
    async def test_matches_anchor_text(self, fake_db):
        fake_db([FakeResult([make_node(node_id=2, anchor_text="部署 手册")])])
        sec = await MysqlGraphService().find_section_by_title("doc1", "部署手册")
        assert sec.node_id == 2

    @pytest.mark.asyncio
    async def test_matches_section_path(self, fake_db):
        fake_db([FakeResult([make_node(node_id=3, section_path="1.1 安装")])])
        sec = await MysqlGraphService().find_section_by_title("doc1", "1.1 安装")
        assert sec.node_id == 3

    @pytest.mark.asyncio
    async def test_no_match(self, fake_db):
        fake_db([FakeResult([make_node(node_id=1, title="别的")])])
        assert await MysqlGraphService().find_section_by_title("doc1", "不匹配") is None


class TestFindSectionByCanonicalPath:
    @pytest.mark.asyncio
    async def test_found_strips(self, fake_db):
        fake_db([FakeResult([make_node(node_id=9)])])
        sec = await MysqlGraphService().find_section_by_canonical_path("doc1", " /1.1 ")
        assert sec.node_id == 9


class TestFindBestSection:
    @pytest.mark.asyncio
    async def test_topic_in_title_wins(self, fake_db):
        nodes = [
            make_node(node_id=1, title="配置数据库", content_text="正文"),
            make_node(node_id=2, title="其他", content_text="配置数据库 相关内容"),
        ]
        fake_db([FakeResult(nodes)])
        sec = await MysqlGraphService().find_best_section("doc1", "配置数据库", "")
        assert sec.node_id == 1

    @pytest.mark.asyncio
    async def test_content_only_lower_score(self, fake_db):
        nodes = [
            make_node(node_id=1, title="其他", content_text="配置数据库 相关内容"),
        ]
        fake_db([FakeResult(nodes)])
        sec = await MysqlGraphService().find_best_section("doc1", "配置数据库", "")
        assert sec.node_id == 1

    @pytest.mark.asyncio
    async def test_facet_boosts(self, fake_db):
        nodes = [
            make_node(node_id=1, title="安装手册", content_text="x"),
            make_node(node_id=2, title="安装", content_text="包含 安装 和 配置 内容"),
        ]
        fake_db([FakeResult(nodes)])
        sec = await MysqlGraphService().find_best_section("doc1", "安装", "配置")
        assert sec.node_id == 2

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, fake_db):
        fake_db([FakeResult([make_node(node_id=1, title="别的")])])
        assert await MysqlGraphService().find_best_section("doc1", "不匹配", "") is None


class TestListSections:
    @pytest.mark.asyncio
    async def test_maps_all(self, fake_db):
        fake_db([FakeResult([make_node(node_id=1), make_node(node_id=2)])])
        out = await MysqlGraphService().list_sections("doc1")
        assert [s.node_id for s in out] == [1, 2]


class TestListChildren:
    @pytest.mark.asyncio
    async def test_delegates(self, fake_db):
        fake_db([FakeResult([make_node(node_id=3)])])
        out = await MysqlGraphService().list_children("doc1", "2")
        assert [s.node_id for s in out] == [3]


class TestParentSection:
    @pytest.mark.asyncio
    async def test_found(self, fake_db):
        fake_db([FakeResult([1]), FakeResult([make_node(node_id=1)])])
        sec = await MysqlGraphService().parent_section("doc1", "2")
        assert sec.node_id == 1

    @pytest.mark.asyncio
    async def test_no_parent(self, fake_db):
        fake_db([FakeResult([None])])
        assert await MysqlGraphService().parent_section("doc1", "2") is None


class TestSiblings:
    @pytest.mark.asyncio
    async def test_previous(self, fake_db):
        fake_db([FakeResult([3]), FakeResult([make_node(node_id=3)])])
        sec = await MysqlGraphService().previous_sibling("doc1", "2")
        assert sec.node_id == 3

    @pytest.mark.asyncio
    async def test_previous_none(self, fake_db):
        fake_db([FakeResult([None])])
        assert await MysqlGraphService().previous_sibling("doc1", "2") is None

    @pytest.mark.asyncio
    async def test_next(self, fake_db):
        fake_db([FakeResult([4]), FakeResult([make_node(node_id=4)])])
        sec = await MysqlGraphService().next_sibling("doc1", "2")
        assert sec.node_id == 4


class TestFindItemByIndex:
    @pytest.mark.asyncio
    async def test_found(self, fake_db):
        fake_db([FakeResult([make_node(node_id=9, node_type=3)])])
        item = await MysqlGraphService().find_item_by_index("doc1", "2", 1)
        assert item.node_id == 9
        assert item.node_type == "STEP"

    @pytest.mark.asyncio
    async def test_not_found(self, fake_db):
        fake_db([FakeResult([])])
        assert await MysqlGraphService().find_item_by_index("doc1", "2", 1) is None


class TestListItems:
    @pytest.mark.asyncio
    async def test_maps_items(self, fake_db):
        fake_db([FakeResult([make_node(node_id=9, node_type=4)])])
        items = await MysqlGraphService().list_items("doc1", "2")
        assert [i.node_id for i in items] == [9]
        assert items[0].node_type == "LIST_ITEM"


class TestSearchItemsInSection:
    @pytest.mark.asyncio
    async def test_no_items_returns_empty(self, fake_db):
        fake_db([FakeResult([])])
        assert await MysqlGraphService().search_items_in_section("doc1", "2", "k") == []

    @pytest.mark.asyncio
    async def test_blank_keyword_returns_all(self, fake_db):
        fake_db([FakeResult([make_node(node_id=1, node_type=3)])])
        items = await MysqlGraphService().search_items_in_section("doc1", "2", "  ")
        assert [i.node_id for i in items] == [1]

    @pytest.mark.asyncio
    async def test_matches_content(self, fake_db):
        fake_db(
            [
                FakeResult(
                    [
                        make_node(node_id=1, node_type=3, content_text="点击 提交 按钮"),
                        make_node(node_id=2, node_type=3, content_text="无关内容"),
                    ]
                )
            ]
        )
        items = await MysqlGraphService().search_items_in_section("doc1", "2", "提交")
        assert [i.node_id for i in items] == [1]
