from collections import deque

import pytest

from app.document.structure.hierarchy import DocumentStructureHierarchyResolver, ListContext
from app.document.structure.models import (
    DocumentStructureNodeDraft,
    DocumentStructureNodeType,
    DocumentStructureSignal,
    DocumentStructureSignalKind,
)


def sig(
    line_no,
    kind,
    text=None,
    node_code="",
    title="",
    level_hint=None,
    indent_level=None,
    item_index=None,
    reasons=None,
    numeric_path=None,
):
    t = text if text is not None else title
    return DocumentStructureSignal(
        line_no=line_no,
        raw_text=t,
        normalized_text=t,
        kind=kind,
        node_code=node_code,
        title=title,
        level_hint=level_hint,
        indent_level=indent_level,
        item_index=item_index,
        reasons=reasons or [],
        numeric_path=numeric_path,
    )


H = DocumentStructureSignalKind.HEADING
HC = DocumentStructureSignalKind.HEADING_CANDIDATE
BODY = DocumentStructureSignalKind.BODY
LIST = DocumentStructureSignalKind.LIST_ITEM
STEP = DocumentStructureSignalKind.STEP_ITEM
BLANK = DocumentStructureSignalKind.BLANK
NOISE = DocumentStructureSignalKind.NOISE
TABLE = DocumentStructureSignalKind.TABLE_ROW
QUOTE = DocumentStructureSignalKind.QUOTE


@pytest.fixture
def resolver():
    return DocumentStructureHierarchyResolver()


def make_heading(text, reasons, node_code="", **kw):
    return sig(
        kw.pop("line_no", 2),
        H,
        title=text,
        node_code=node_code,
        reasons=reasons,
        **kw,
    )


class TestResolveBasics:
    def test_empty_signals_has_root(self, resolver):
        drafts = resolver.resolve("我的文档", [])
        assert len(drafts) == 1
        root = drafts[0]
        assert root.node_no == 1
        assert root.node_type == DocumentStructureNodeType.DOCUMENT.value
        assert root.depth == 0
        assert root.parent_node_no is None
        assert root.title == "我的文档"
        assert root.canonical_path == "/document"

    def test_root_title_fallback(self, resolver):
        drafts = resolver.resolve("", [])
        assert drafts[0].title == "文档"

    def test_line_no_zero_skipped(self, resolver):
        drafts = resolver.resolve("文档", [sig(0, BODY, text="跳过")])
        assert len(drafts) == 1

    def test_none_signal_skipped(self, resolver):
        drafts = resolver.resolve("文档", [None])
        assert len(drafts) == 1

    def test_noise_ignored(self, resolver):
        drafts = resolver.resolve("文档", [sig(1, NOISE, text="噪音")])
        assert len(drafts) == 1

    def test_heading_creates_section(self, resolver):
        drafts = resolver.resolve("文档", [make_heading("第一章", ["chapter-heading"])])
        assert len(drafts) == 2
        sec = drafts[1]
        assert sec.node_type == DocumentStructureNodeType.SECTION.value
        assert sec.parent_node_no == 1
        assert sec.depth == 1
        assert sec.source_family == "chapter"

    def test_heading_candidate_also_section(self, resolver):
        drafts = resolver.resolve(
            "文档", [sig(2, HC, title="疑似标题", reasons=["single-digit-ambiguous-heading"])]
        )
        assert len(drafts) == 2
        assert drafts[1].node_type == DocumentStructureNodeType.SECTION.value

    def test_body_goes_to_root_without_section(self, resolver):
        drafts = resolver.resolve("文档", [sig(1, BODY, text="正文")])
        assert drafts[0]._content_lines == ["正文"]

    def test_body_goes_to_current_section(self, resolver):
        signals = [
            make_heading("第一章", ["chapter-heading"], line_no=1),
            sig(2, BODY, text="第一章正文"),
        ]
        drafts = resolver.resolve("文档", signals)
        assert drafts[1]._content_lines == ["第一章", "第一章正文"]

    def test_nodes_sorted_by_node_no(self, resolver):
        signals = [
            sig(5, BODY, text="后"),
            make_heading("第一章", ["chapter-heading"], line_no=1),
        ]
        drafts = resolver.resolve("文档", signals)
        node_nos = [d.node_no for d in drafts]
        assert node_nos == sorted(node_nos)


class TestListHandling:
    def test_list_item_created(self, resolver):
        drafts = resolver.resolve(
            "文档", [sig(1, LIST, title="条目A", indent_level=0)]
        )
        item = drafts[1]
        assert item.node_type == DocumentStructureNodeType.LIST_ITEM.value
        assert item.parent_node_no == 1
        assert item.source_family == "list"
        assert item.depth == 1

    def test_step_item_created(self, resolver):
        drafts = resolver.resolve(
            "文档", [sig(1, STEP, title="第一步", item_index=1, indent_level=0)]
        )
        step = drafts[1]
        assert step.node_type == DocumentStructureNodeType.STEP.value
        assert step.source_family == "step"
        assert step.node_code == "1"
        assert step.item_index == 1

    def test_nested_list_parent(self, resolver):
        signals = [
            sig(1, LIST, title="父项", indent_level=0),
            sig(2, LIST, title="子项", indent_level=1),
        ]
        drafts = resolver.resolve("文档", signals)
        assert drafts[2].parent_node_no == 2

    def test_dedent_list_returns_to_section(self, resolver):
        signals = [
            sig(1, LIST, title="一级", indent_level=0),
            sig(2, LIST, title="二级", indent_level=1),
            sig(3, LIST, title="新一级", indent_level=0),
        ]
        drafts = resolver.resolve("文档", signals)
        assert drafts[3].parent_node_no == 1

    def test_list_blank_resets_stack(self, resolver):
        signals = [
            sig(1, LIST, title="一级", indent_level=0),
            sig(2, BLANK, text=""),
            sig(3, LIST, title="新项", indent_level=0),
        ]
        drafts = resolver.resolve("文档", signals)
        assert drafts[2].parent_node_no == 1

    def test_list_text_appended_to_section(self, resolver):
        signals = [
            make_heading("第一章", ["chapter-heading"], line_no=1),
            sig(2, LIST, title="条目", indent_level=0),
        ]
        drafts = resolver.resolve("文档", signals)
        assert "条目" in drafts[1]._content_lines

    def test_body_after_list_goes_to_list_and_section(self, resolver):
        signals = [
            make_heading("第一章", ["chapter-heading"], line_no=1),
            sig(2, LIST, title="条目", indent_level=0),
            sig(3, BODY, text="条目补充"),
        ]
        drafts = resolver.resolve("文档", signals)
        assert "条目补充" in drafts[2]._content_lines
        assert "条目补充" in drafts[1]._content_lines

    def test_heading_clears_list_context(self, resolver):
        signals = [
            sig(1, LIST, title="条目", indent_level=0),
            make_heading("第一章", ["chapter-heading"], line_no=2),
            sig(3, BODY, text="章正文"),
        ]
        drafts = resolver.resolve("文档", signals)
        assert drafts[2]._content_lines == ["第一章", "章正文"]

    def test_node_code_from_signal(self, resolver):
        drafts = resolver.resolve(
            "文档", [sig(1, LIST, title="条目", node_code="1.1", indent_level=0)]
        )
        assert drafts[1].node_code == "1.1"


class TestResolveListParent:
    def test_parent_is_section_when_no_stack(self, resolver):
        node = DocumentStructureNodeDraft(node_no=5, title="节")
        parent = resolver._resolve_list_parent(sig(1, LIST, indent_level=0), node, deque(), node)
        assert parent == node

    def test_deeper_indent_takes_stack_top(self, resolver):
        section = DocumentStructureNodeDraft(node_no=5, title="节")
        top = DocumentStructureNodeDraft(node_no=6, title="顶")
        stack = deque([ListContext(node=top, indent_level=0)])
        parent = resolver._resolve_list_parent(sig(1, LIST, indent_level=1), section, stack, section)
        assert parent == top

    def test_same_indent_pops_and_returns_section(self, resolver):
        section = DocumentStructureNodeDraft(node_no=5, title="节")
        top = DocumentStructureNodeDraft(node_no=6, title="顶")
        stack = deque([ListContext(node=top, indent_level=0)])
        parent = resolver._resolve_list_parent(sig(1, LIST, indent_level=0), section, stack, section)
        assert parent == section

    def test_negative_indent_safe(self, resolver):
        section = DocumentStructureNodeDraft(node_no=5, title="节")
        parent = resolver._resolve_list_parent(sig(1, LIST, indent_level=-3), section, deque(), section)
        assert parent == section


class TestHeadingDepth:
    def test_markdown_depth_from_level(self, resolver):
        sig_ = make_heading("## 标题", ["markdown-heading"], level_hint=2)
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 2

    def test_chapter_depth_one(self, resolver):
        sig_ = make_heading("第一章", ["chapter-heading"])
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 1

    def test_appendix_depth_one(self, resolver):
        sig_ = make_heading("附录A", ["appendix-heading"])
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 1

    def test_decimal_single_level(self, resolver):
        sig_ = make_heading("1. 概述", ["decimal-heading"], numeric_path=[1])
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 1

    def test_decimal_nested_with_parent(self, resolver):
        parent = DocumentStructureNodeDraft(node_no=2, depth=1)
        drafts = [parent]
        latest_by_num = {"1": 2}
        sig_ = make_heading("1.1 细目", ["decimal-heading"], numeric_path=[1, 1])
        assert resolver._resolve_heading_depth(sig_, drafts, {}, latest_by_num) == 2

    def test_decimal_nested_without_parent_falls_back_to_len(self, resolver):
        sig_ = make_heading("1.2.3 条目", ["decimal-heading"], numeric_path=[1, 2, 3])
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 3

    def test_plain_falls_back_to_level(self, resolver):
        sig_ = make_heading("标题", ["other"], level_hint=3)
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 3

    def test_plain_default_level(self, resolver):
        sig_ = make_heading("标题", [])
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 1

    def test_markdown_clamps_to_min_1(self, resolver):
        sig_ = make_heading("标题", ["markdown-heading"], level_hint=0)
        assert resolver._resolve_heading_depth(sig_, [], {}, {}) == 1


class TestHeadingParent:
    def test_chapter_parent_is_root(self, resolver):
        sig_ = make_heading("第一章", ["chapter-heading"])
        assert resolver._resolve_heading_parent_node_no(sig_, 1, {}, {}) == 1

    def test_decimal_exact_parent(self, resolver):
        sig_ = make_heading("1.2 节", ["decimal-heading"], numeric_path=[1, 2])
        assert resolver._resolve_heading_parent_node_no(sig_, 2, {}, {"1": 7}) == 7

    def test_decimal_chapter_fallback(self, resolver):
        sig_ = make_heading("1.2 节", ["decimal-heading"], numeric_path=[1, 2])
        assert resolver._resolve_heading_parent_node_no(sig_, 2, {}, {"1": 3}) == 3

    def test_nearest_parent_by_depth(self, resolver):
        sig_ = make_heading("标题", ["plain"])
        latest = {1: 2, 2: 5}
        assert resolver._resolve_heading_parent_node_no(sig_, 3, latest, {}) == 5

    def test_no_parent_returns_root(self, resolver):
        sig_ = make_heading("标题", [])
        assert resolver._resolve_heading_parent_node_no(sig_, 2, {}, {}) == 1


class TestHeadingRegistry:
    def test_depth_registry_pruned(self, resolver):
        drafts = resolver.resolve(
            "文档",
            [
                make_heading("1 章", ["decimal-heading"], numeric_path=[1], line_no=1),
                make_heading("1.1 节", ["decimal-heading"], numeric_path=[1, 1], line_no=2),
                make_heading("2 章", ["decimal-heading"], numeric_path=[2], line_no=3),
            ],
        )
        assert drafts[1].depth == 1
        assert drafts[2].depth == 2
        assert drafts[3].depth == 1

    def test_numeric_path_tracked(self, resolver):
        signals = [
            make_heading("1 章", ["decimal-heading"], numeric_path=[1], line_no=1),
            make_heading("1.1 节", ["decimal-heading"], numeric_path=[1, 1], line_no=2),
        ]
        drafts = resolver.resolve("文档", signals)
        assert drafts[2].numeric_path == [1, 1]
        assert drafts[2].parent_node_no == 2


class TestHeadingAnchorText:
    def test_no_code_returns_title(self, resolver):
        sig_ = make_heading("标题", [])
        assert resolver._build_heading_anchor_text(sig_) == "标题"

    def test_title_prefixed_with_code(self, resolver):
        sig_ = make_heading("1.1 细目", ["decimal-heading"], node_code="1.1")
        assert resolver._build_heading_anchor_text(sig_) == "1.1 细目"

    def test_code_title_joined(self, resolver):
        sig_ = make_heading("细目", ["decimal-heading"], node_code="1.1")
        assert resolver._build_heading_anchor_text(sig_) == "1.1 细目"


class TestNumericKey:
    def test_empty(self, resolver):
        assert resolver._numeric_key([]) == ""

    def test_join(self, resolver):
        assert resolver._numeric_key([1, 2, 3]) == "1.2.3"


class TestSafeHelpers:
    def test_safe_level_default(self, resolver):
        assert resolver._safe_level(None, 2) == 2
        assert resolver._safe_level(0, 2) == 2
        assert resolver._safe_level(-1, 2) == 2

    def test_safe_level_valid(self, resolver):
        assert resolver._safe_level(3, 2) == 3

    def test_safe_indent_default(self, resolver):
        assert resolver._safe_indent_level(sig(1, LIST, indent_level=None)) == 0
        assert resolver._safe_indent_level(sig(1, LIST, indent_level=-5)) == 0

    def test_safe_indent_valid(self, resolver):
        assert resolver._safe_indent_level(sig(1, LIST, indent_level=2)) == 2


class TestFindByNodeNo:
    def test_found(self, resolver):
        drafts = [DocumentStructureNodeDraft(node_no=3, title="三")]
        assert resolver._find_by_node_no(drafts, 3).title == "三"

    def test_not_found(self, resolver):
        assert resolver._find_by_node_no([DocumentStructureNodeDraft(node_no=3)], 9) is None
