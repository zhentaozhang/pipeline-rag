import pytest

from app.document.structure.models import DocumentStructureNodeDraft
from app.document.structure.validator import DocumentStructureTreeValidator


@pytest.fixture
def validator():
    return DocumentStructureTreeValidator()


def draft(node_no, node_type="section", parent=None, title="", code="", line_no=0, numeric_path=None, item_index=None):
    d = DocumentStructureNodeDraft(
        node_no=node_no,
        line_no=line_no,
        node_type=node_type,
        parent_node_no=parent,
        node_code=code,
        title=title,
        numeric_path=numeric_path or [],
        item_index=item_index,
    )
    return d


class TestValidateAndBuild:
    def test_empty_drafts(self, validator):
        assert validator.validate_and_build("标题", []) == []

    def test_returns_ordered_candidates(self, validator):
        drafts = [
            draft(2, parent=1, title="第二章"),
            draft(3, parent=1, title="第三章"),
            draft(1, node_type="document", title="文档"),
        ]
        candidates = validator.validate_and_build("文档", drafts)
        assert [c.node_no for c in candidates] == [1, 2, 3]

    def test_root_is_document(self, validator):
        candidates = validator.validate_and_build("文档", [draft(1, node_type="document", title="文档")])
        assert len(candidates) == 1
        assert candidates[0].node_type == "document"
        assert candidates[0].depth == 0
        assert candidates[0].canonical_path == "/document"
        assert candidates[0].section_path == ""


class TestCollapseSyntheticTitleSection:
    def test_duplicate_title_section_removed(self, validator):
        drafts = {
            1: draft(1, node_type="document", title="安装指南"),
            2: draft(2, parent=1, title="安装指南"),
            3: draft(3, parent=2, title="子内容"),
            4: draft(4, parent=1, title="正常章节"),
        }
        validator._collapse_synthetic_title_section("安装指南", drafts)
        assert 2 not in drafts
        assert drafts[3].parent_node_no == 1
        assert drafts[4].parent_node_no == 1

    def test_matching_normalization(self, validator):
        drafts = {
            1: draft(1, node_type="document", title="安装指南.pdf"),
            2: draft(2, parent=1, title="# 安装指南"),
        }
        validator._collapse_synthetic_title_section("安装指南.pdf", drafts)
        assert 2 not in drafts

    def test_section_with_code_not_collapsed(self, validator):
        drafts = {
            1: draft(1, node_type="document", title="安装指南"),
            2: draft(2, parent=1, title="安装指南", code="第一章"),
        }
        validator._collapse_synthetic_title_section("安装指南", drafts)
        assert 2 in drafts

    def test_root_title_section_untouched(self, validator):
        drafts = {
            1: draft(1, node_type="document", title="安装指南"),
            2: draft(2, parent=1, title="安装指南"),
        }
        validator._collapse_synthetic_title_section("安装指南", drafts)
        assert 1 in drafts
        assert 2 not in drafts

    def test_empty_document_title_skips(self, validator):
        drafts = {
            1: draft(1, node_type="document", title="安装指南"),
            2: draft(2, parent=1, title="安装指南"),
        }
        validator._collapse_synthetic_title_section("", drafts)
        assert 2 in drafts


class TestRepairNumberedHierarchy:
    def test_single_level_parents_rooted(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=99, title="第一章", numeric_path=[1]),
            3: draft(3, parent=99, title="第二章", numeric_path=[2]),
        }
        validator._repair_numbered_hierarchy(drafts)
        assert drafts[2].parent_node_no == 1
        assert drafts[3].parent_node_no == 1

    def test_direct_parent_by_numeric_path(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="第一章", numeric_path=[1]),
            3: draft(3, parent=99, title="1.1 小节", numeric_path=[1, 1]),
        }
        validator._repair_numbered_hierarchy(drafts)
        assert drafts[3].parent_node_no == 2

    def test_chapter_fallback_when_direct_parent_missing(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="第一章", numeric_path=[1]),
            3: draft(3, parent=99, title="1.2 小节", numeric_path=[1, 2]),
        }
        validator._repair_numbered_hierarchy(drafts)
        assert drafts[3].parent_node_no == 2

    def test_no_parent_found_keeps_original(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            3: draft(3, parent=99, title="2.1 小节", numeric_path=[2, 1]),
        }
        validator._repair_numbered_hierarchy(drafts)
        assert drafts[3].parent_node_no == 99

    def test_no_numeric_path_untouched(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=7, title="无编号"),
        }
        validator._repair_numbered_hierarchy(drafts)
        assert drafts[2].parent_node_no == 7


class TestRepairInvalidParents:
    def test_missing_parent_roots(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=99, title="孤儿"),
        }
        validator._repair_invalid_parents(drafts)
        assert drafts[2].parent_node_no == 1

    def test_none_parent_roots(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=None, title="无父"),
        }
        validator._repair_invalid_parents(drafts)
        assert drafts[2].parent_node_no == 1

    def test_section_under_list_like_promoted(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, node_type="list_item", parent=1, title="条目"),
            3: draft(3, parent=2, title="误挂在条目下的节"),
        }
        validator._repair_invalid_parents(drafts)
        assert drafts[3].parent_node_no == 1

    def test_section_under_list_like_with_grandparent(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="节"),
            3: draft(3, node_type="step", parent=2, title="步骤"),
            4: draft(4, parent=3, title="误挂的节"),
        }
        validator._repair_invalid_parents(drafts)
        assert drafts[4].parent_node_no == 2

    def test_root_untouched(self, validator):
        drafts = {1: draft(1, node_type="document", parent=None)}
        validator._repair_invalid_parents(drafts)
        assert drafts[1].parent_node_no is None

    def test_list_like_child_kept(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, node_type="list_item", parent=1, title="条目"),
        }
        validator._repair_invalid_parents(drafts)
        assert drafts[2].parent_node_no == 1


class TestRecomputeDepths:
    def test_chain_depths(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="节"),
            3: draft(3, parent=2, title="子节"),
        }
        validator._recompute_depths(drafts)
        assert drafts[1].depth == 0
        assert drafts[2].depth == 1
        assert drafts[3].depth == 2

    def test_missing_root_skips(self, validator):
        drafts = {2: draft(2, parent=1, title="节")}
        validator._recompute_depths(drafts)
        assert drafts[2].depth == 0

    def test_missing_parent_depth_one(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=99, title="节"),
        }
        validator._recompute_depths(drafts)
        assert drafts[2].depth == 1


class TestRebuildPaths:
    def test_canonical_and_section_paths(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="第一章", code="第一章"),
            3: draft(3, parent=2, title="1.1 小节", code="1.1"),
        }
        validator._rebuild_paths("文档", drafts)
        assert drafts[2].canonical_path == "/document/第一章"
        assert drafts[2].section_path == "第一章"
        assert drafts[3].canonical_path == "/document/第一章/1.1"
        assert drafts[3].section_path == "第一章 > 1.1 小节"

    def test_title_section_path_uses_display_title(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="安装", code="1"),
        }
        validator._rebuild_paths("文档", drafts)
        assert drafts[2].section_path == "1 安装"

    def test_list_item_path_segment(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, node_type="list_item", parent=1, title="条目", item_index=3),
            3: draft(3, node_type="list_item", parent=1, title="无编号条目"),
        }
        validator._rebuild_paths("文档", drafts)
        assert drafts[2].canonical_path == "/document/item-3"
        assert drafts[3].canonical_path == "/document/无编号条目"

    def test_non_section_inherits_section_path(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="第一章"),
            3: draft(3, node_type="body", parent=2, title="正文"),
        }
        validator._rebuild_paths("文档", drafts)
        assert drafts[3].section_path == "第一章"

    def test_orphan_parents_rooted_path(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=99, title="孤节"),
        }
        validator._rebuild_paths("文档", drafts)
        assert drafts[2].canonical_path == "/document/孤节"


class TestRebuildSiblingLinks:
    def test_links_sorted_by_line_no(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="乙", line_no=2),
            3: draft(3, parent=1, title="甲", line_no=1),
        }
        validator._rebuild_sibling_links(drafts)
        assert drafts[3].prev_sibling_node_no == 0
        assert drafts[3].next_sibling_node_no == 2
        assert drafts[2].prev_sibling_node_no == 3
        assert drafts[2].next_sibling_node_no == 0

    def test_single_child_no_siblings(self, validator):
        drafts = {
            1: draft(1, node_type="document"),
            2: draft(2, parent=1, title="独子"),
        }
        validator._rebuild_sibling_links(drafts)
        assert drafts[2].prev_sibling_node_no == 0
        assert drafts[2].next_sibling_node_no == 0


class TestBuildPathSegment:
    def test_list_like_with_index(self, validator):
        d = draft(2, node_type="list_item", item_index=5)
        assert validator._build_path_segment(d) == "item-5"

    def test_list_like_without_index_uses_title(self, validator):
        d = draft(2, node_type="list_item", title="普通条目")
        assert validator._build_path_segment(d) == "普通条目"

    def test_section_with_code(self, validator):
        d = draft(2, code="1.1", title="小节")
        assert validator._build_path_segment(d) == "1.1"

    def test_section_without_code_uses_title(self, validator):
        d = draft(2, title="自由标题")
        assert validator._build_path_segment(d) == "自由标题"

    def test_none_draft(self, validator):
        assert validator._build_path_segment(None) == "node"


class TestDisplayTitle:
    def test_no_code(self, validator):
        d = draft(2, title="标题")
        assert validator._display_title(d) == "标题"

    def test_title_starts_with_code(self, validator):
        d = draft(2, code="1.1", title="1.1 小节")
        assert validator._display_title(d) == "1.1 小节"

    def test_title_prefixed_with_code(self, validator):
        d = draft(2, code="第一章", title="总览")
        assert validator._display_title(d) == "第一章 总览"


class TestSlug:
    def test_whitespace_to_dash(self, validator):
        assert validator._slug("hello world") == "hello-world"

    def test_keeps_cjk_and_ascii(self, validator):
        assert validator._slug("安装-guide 1.2") == "安装-guide-1.2"

    def test_strips_special_chars(self, validator):
        assert validator._slug("a!@#b") == "ab"

    def test_strips_url_unsafe_punctuation(self, validator):
        assert validator._slug("a:b?c@d") == "abcd"

    def test_keeps_dot_and_dash(self, validator):
        assert validator._slug("1.1 安装-指南") == "1.1-安装-指南"

    def test_empty_fallback(self, validator):
        assert validator._slug("") == "node"
        assert validator._slug(None) == "node"

    def test_pure_special_chars_fallback(self, validator):
        assert validator._slug("!!!") == "node"


class TestJoinSectionPath:
    def test_empty_parent(self, validator):
        assert validator._join_section_path("", "章节") == "章节"

    def test_empty_current(self, validator):
        assert validator._join_section_path("父", "") == "父"

    def test_nested(self, validator):
        assert validator._join_section_path("甲 > 乙", "丙") == "甲 > 乙 > 丙"


class TestNumericKey:
    def test_join(self, validator):
        assert validator._numeric_key([1, 2, 3]) == "1.2.3"

    def test_empty(self, validator):
        assert validator._numeric_key([]) == ""


class TestToCandidate:
    def test_sibling_normalization(self, validator):
        d = draft(2, parent=1, title="节")
        d.prev_sibling_node_no = None
        d.next_sibling_node_no = None
        c = validator._to_candidate(d)
        assert c.prev_sibling_node_no == 0
        assert c.next_sibling_node_no == 0

    def test_content_text(self, validator):
        d = draft(2, parent=1, title="节")
        d.append_line("第一行")
        d.append_line("")
        d.append_line("第二行")
        c = validator._to_candidate(d)
        assert c.content_text == "第一行\n第二行"

    def test_field_mapping(self, validator):
        d = draft(2, node_type="list_item", parent=1, title="条目", item_index=4, line_no=9)
        d.anchor_text = "锚点"
        d.depth = 2
        d.canonical_path = "/document/x"
        d.section_path = "节"
        c = validator._to_candidate(d)
        assert c.node_no == 2
        assert c.node_type == "list_item"
        assert c.parent_node_no == 1
        assert c.item_index == 4
        assert c.anchor_text == "锚点"
        assert c.depth == 2
        assert c.canonical_path == "/document/x"
        assert c.section_path == "节"


class TestNormalizeComparableTitle:
    def test_strips_marks_and_extension(self, validator):
        assert validator._normalize_comparable_title("# 安装指南.PDF") == "安装指南"

    def test_strips_whitespace_and_lower(self, validator):
        assert validator._normalize_comparable_title(" 安装 指南 ") == "安装指南"

    def test_empty(self, validator):
        assert validator._normalize_comparable_title("") == ""
        assert validator._normalize_comparable_title(None) == ""


class TestValidateAndBuildEndToEnd:
    def test_full_flow(self, validator):
        drafts = [
            draft(1, node_type="document", title="安装指南"),
            draft(2, parent=1, title="第一章", code="第一章", numeric_path=[1], line_no=1),
            draft(3, parent=2, title="1.1 小节", code="1.1", numeric_path=[1, 1], line_no=2),
            draft(4, parent=99, title="1.2 小节", code="1.2", numeric_path=[1, 2], line_no=3),
        ]
        candidates = validator.validate_and_build("安装指南", drafts)
        by_no = {c.node_no: c for c in candidates}
        assert len(candidates) == 4
        assert by_no[1].depth == 0
        assert by_no[2].depth == 1
        assert by_no[3].depth == 2
        assert by_no[4].parent_node_no == 2
        assert by_no[4].depth == 2
        assert by_no[3].canonical_path == "/document/第一章/1.1"
        assert by_no[3].section_path == "第一章 > 1.1 小节"
