import types

import pytest

from app.document.structure.extractors import DocumentStructureSignalExtractor
from app.document.structure.extractors.base import (
    build_context,
    build_line_frequency,
    build_logical_lines,
    count_indent_level,
    safe_text,
)
from app.document.structure.models import (
    DocumentStructureLogicalLine,
    DocumentStructureSignalKind,
)


def make_properties(**overrides):
    defaults = dict(max_plain_heading_chars=32)
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr(
        "app.document.structure.extractors.get_settings",
        lambda: types.SimpleNamespace(structure=make_properties()),
    )
    return DocumentStructureSignalExtractor()


def ll(line_no, text, indent=0, raw=None):
    return DocumentStructureLogicalLine(
        line_no=line_no,
        raw_line_index=line_no,
        segment_index=1,
        indent_level=indent,
        raw_text=raw if raw is not None else text,
        normalized_text=text,
    )


class TestBuildLogicalLines:
    def test_empty_text_produces_one_blank_line(self):
        for text in ("", None):
            lines = build_logical_lines(text)
            assert len(lines) == 1
            assert lines[0].normalized_text == ""

    def test_multiple_lines(self):
        lines = build_logical_lines("第一行\n\n第三行")
        assert len(lines) == 3
        assert [line.normalized_text for line in lines] == ["第一行", "", "第三行"]

    def test_line_numbers(self):
        lines = build_logical_lines("a\nb")
        assert [line.line_no for line in lines] == [1, 2]
        assert [line.raw_line_index for line in lines] == [1, 2]

    def test_indent_level_tracked(self):
        lines = build_logical_lines("  缩进行")
        assert lines[0].indent_level == 2

    def test_markdown_not_split(self):
        lines = build_logical_lines("# 标题 第1步 内容")
        assert len(lines) == 1

    def test_inline_steps_split(self):
        lines = build_logical_lines("第1步：初始化环境。第2步：配置参数。")
        assert len(lines) == 2
        assert lines[0].normalized_text == "第1步：初始化环境。"
        assert lines[1].normalized_text == "第2步：配置参数。"

    def test_inline_steps_without_punctuation_not_split(self):
        lines = build_logical_lines("第1步 初始化环境。第2步 配置参数。")
        assert len(lines) == 1

    def test_table_row_not_split(self):
        lines = build_logical_lines("| 列A | 列B |")
        assert len(lines) == 1

    def test_separator_line_not_split(self):
        lines = build_logical_lines("----")
        assert len(lines) == 1


class TestCountIndentLevel:
    def test_spaces(self):
        assert count_indent_level("  abc") == 2

    def test_tabs_count_as_four(self):
        assert count_indent_level("\tabc") == 4
        assert count_indent_level("\t\tabc") == 8

    def test_mixed(self):
        assert count_indent_level(" \t abc") == 6

    def test_no_indent(self):
        assert count_indent_level("abc") == 0
        assert count_indent_level("") == 0


class TestBuildLineFrequency:
    def test_counts_normalized_lines(self):
        lines = [ll(1, "a"), ll(2, "a"), ll(3, "b")]
        assert build_line_frequency(lines) == {"a": 2, "b": 1}

    def test_empty_text_skipped(self):
        lines = [ll(1, "")]
        assert build_line_frequency(lines) == {}


class TestBuildContext:
    def test_prev_and_next(self):
        lines = [ll(1, "上一行"), ll(2, "当前"), ll(3, "下一行")]
        ctx = build_context(lines, 1)
        assert ctx.previous_non_blank.normalized_text == "上一行"
        assert ctx.next_non_blank.normalized_text == "下一行"
        assert not ctx.blank_before
        assert not ctx.blank_after

    def test_blank_flags(self):
        lines = [ll(1, ""), ll(2, ""), ll(3, "当前"), ll(4, ""), ll(5, "下一")]
        ctx = build_context(lines, 2)
        assert ctx.blank_before
        assert ctx.blank_after
        assert ctx.previous_non_blank is None

    def test_bounds(self):
        lines = [ll(1, "首"), ll(2, "次")]
        ctx = build_context(lines, 0)
        assert ctx.previous_non_blank is None
        ctx = build_context(lines, 1)
        assert ctx.next_non_blank is None


class TestSafeText:
    def test_strips(self):
        assert safe_text("  x  ") == "x"
        assert safe_text(None) == ""
        assert safe_text("") == ""


class TestExtractBasics:
    def test_empty_text_has_title_signal(self, extractor):
        batch = extractor.extract("我的文档", "")
        kinds = [s.kind for s in batch.signals]
        assert kinds == [
            DocumentStructureSignalKind.DOCUMENT_TITLE,
            DocumentStructureSignalKind.BLANK,
        ]

    def test_blank_lines(self, extractor):
        batch = extractor.extract("", "\n\n")
        kinds = [s.kind for s in batch.signals]
        assert kinds == [
            DocumentStructureSignalKind.BLANK,
            DocumentStructureSignalKind.BLANK,
            DocumentStructureSignalKind.BLANK,
        ]

    def test_context_lines(self, extractor):
        batch = extractor.extract("", "a\nb")
        assert batch.context_lines == ["a", "b"]


class TestExtractKinds:
    def test_markdown_heading(self, extractor):
        batch = extractor.extract("", "# 一级标题")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.HEADING
        assert sig.reasons == ["markdown-heading"]
        assert sig.level_hint == 1

    def test_duplicate_document_title_noise(self, extractor):
        batch = extractor.extract("安装指南", "# 安装指南")
        assert batch.signals[0].kind == DocumentStructureSignalKind.DOCUMENT_TITLE
        sig = batch.signals[1]
        assert sig.kind == DocumentStructureSignalKind.NOISE
        assert sig.reasons == ["duplicate-document-title"]

    def test_explicit_step(self, extractor):
        batch = extractor.extract("", "第1步 初始化环境")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.STEP_ITEM
        assert sig.reasons == ["explicit-step"]
        assert sig.item_index == 1
        assert sig.title == "初始化环境"

    def test_chapter_heading(self, extractor):
        batch = extractor.extract("", "第一章 概述")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.HEADING
        assert sig.reasons == ["chapter-heading"]
        assert sig.numeric_path == [1]

    def test_appendix_heading(self, extractor):
        batch = extractor.extract("", "附录A")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.HEADING
        assert sig.reasons == ["appendix-heading"]

    def test_decimal_heading(self, extractor):
        batch = extractor.extract("", "1.1 安装部署")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.HEADING
        assert sig.reasons == ["decimal-heading"]
        assert sig.numeric_path == [1, 1]

    def test_table_row(self, extractor):
        batch = extractor.extract("", "| 列A | 列B |")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.TABLE_ROW
        assert sig.reasons == ["table-row"]

    def test_tab_separated_table(self, extractor):
        batch = extractor.extract("", "a\tb\tc")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.TABLE_ROW

    def test_quote(self, extractor):
        batch = extractor.extract("", "> 引用内容")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.QUOTE

    def test_checkbox(self, extractor):
        batch = extractor.extract("", "[x] 完成任务")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.LIST_ITEM
        assert sig.reasons == ["checkbox-list"]
        assert sig.title == "完成任务"

    def test_dash_checkbox_unticked_is_bullet(self, extractor):
        batch = extractor.extract("", "- [x] 完成任务")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.LIST_ITEM
        assert sig.reasons == ["bullet-list"]

    def test_bullet(self, extractor):
        batch = extractor.extract("", "- 条目内容")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.LIST_ITEM
        assert sig.reasons == ["bullet-list"]

    def test_body(self, extractor):
        batch = extractor.extract("", "普通正文段落")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.BODY
        assert sig.reasons == ["body"]

    def test_page_noise(self, extractor):
        batch = extractor.extract("", "第 12 页")
        sig = batch.signals[0]
        assert sig.kind == DocumentStructureSignalKind.NOISE
        assert sig.reasons == ["page-noise"]


class TestExtractAmbiguousHeading:
    def test_single_digit_isolated_heading(self, extractor):
        text = "\n1. 概述\n这是章节正文内容"
        batch = extractor.extract("", text)
        sigs = [s for s in batch.signals if s.kind == DocumentStructureSignalKind.HEADING_CANDIDATE]
        assert len(sigs) == 1
        assert sigs[0].reasons == ["single-digit-ambiguous-heading"]
        assert sigs[0].numeric_path == [1]

    def test_single_digit_sequence_is_list(self, extractor):
        text = "1. 第一步操作\n2. 第二步操作"
        batch = extractor.extract("", text)
        kinds = [s.kind for s in batch.signals]
        assert kinds == [
            DocumentStructureSignalKind.LIST_ITEM,
            DocumentStructureSignalKind.LIST_ITEM,
        ]
        assert batch.signals[0].reasons == ["single-digit-sequence-list"]

    def test_chinese_outline_isolated_heading(self, extractor):
        text = "\n一、概述\n这是章节正文"
        batch = extractor.extract("", text)
        sigs = [s for s in batch.signals if s.kind == DocumentStructureSignalKind.HEADING_CANDIDATE]
        assert len(sigs) == 1
        assert sigs[0].reasons == ["chinese-outline-ambiguous-heading"]

    def test_introduced_list_after_colon(self, extractor):
        text = "清单如下：\n1. 项目甲\n2. 项目乙"
        batch = extractor.extract("", text)
        kinds = [s.kind for s in batch.signals]
        assert kinds[1] == DocumentStructureSignalKind.LIST_ITEM
        assert kinds[2] == DocumentStructureSignalKind.LIST_ITEM

    def test_repeated_header_noise(self, extractor):
        text = "内部资料 | 第1页\n内部资料 | 第1页\n内部资料 | 第1页\n正文开始"
        batch = extractor.extract("", text)
        kinds = [s.kind for s in batch.signals]
        assert kinds[0] == DocumentStructureSignalKind.NOISE
        assert kinds[0] == kinds[1] == kinds[2]


class TestExtractHelpers:
    def test_extract_code_decimal(self, extractor):
        assert extractor._extract_code("1.2 节") == "1.2"

    def test_extract_code_chapter(self, extractor):
        assert extractor._extract_code("第一章 概述") == "第一章"

    def test_extract_code_appendix(self, extractor):
        assert extractor._extract_code("附录B") == "附录B"

    def test_extract_code_none(self, extractor):
        assert extractor._extract_code("普通标题") == ""

    def test_extract_numeric_path_dotted(self, extractor):
        assert extractor._extract_numeric_path("1.2.3") == [1, 2, 3]

    def test_extract_numeric_path_non_digit(self, extractor):
        assert extractor._extract_numeric_path("1.a.3") == []

    def test_extract_numeric_path_chapter(self, extractor):
        assert extractor._extract_numeric_path("第二章") == [2]

    def test_extract_numeric_path_empty(self, extractor):
        assert extractor._extract_numeric_path("") == []

    def test_is_table_row(self, extractor):
        assert extractor._is_table_row("| a | b |")
        assert extractor._is_table_row("a\tb")
        assert extractor._is_table_row("|--|--|")
        assert extractor._is_table_row("----")
        assert not extractor._is_table_row("普通文本")

    def test_infer_level_with_blank_before(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "标题")], 1)
        assert extractor._infer_plain_heading_level(ctx) == 1

    def test_infer_level_without_blank(self, extractor):
        ctx = build_context([ll(1, "上"), ll(2, "标题")], 1)
        assert extractor._infer_plain_heading_level(ctx) == 2

    def test_previous_introduces_list(self, extractor):
        assert extractor._previous_introduces_list(ll(1, "如下："))
        assert extractor._previous_introduces_list(ll(1, "如下:"))
        assert not extractor._previous_introduces_list(ll(1, "正文"))
        assert not extractor._previous_introduces_list(None)

    def test_resolve_ordered_index_arabic(self, extractor):
        assert extractor._resolve_ordered_index("2. 内容", "ARABIC_SINGLE") == 2

    def test_resolve_ordered_index_chinese(self, extractor):
        assert extractor._resolve_ordered_index("二、内容", "CHINESE_OUTLINE") == 2

    def test_resolve_ordered_index_unknown_family(self, extractor):
        assert extractor._resolve_ordered_index("2. 内容", "OTHER") is None

    def test_parse_loose_number_arabic(self, extractor):
        assert extractor._parse_loose_number("5") == 5

    def test_parse_loose_number_chinese(self, extractor):
        assert extractor._parse_loose_number("一") == 1
        assert extractor._parse_loose_number("十") == 10
        assert extractor._parse_loose_number("十一") == 11
        assert extractor._parse_loose_number("二十") == 20
        assert extractor._parse_loose_number("二十一") == 21

    def test_parse_loose_number_invalid(self, extractor):
        assert extractor._parse_loose_number("abc") is None
        assert extractor._parse_loose_number("") is None

    def test_same_document_title(self, extractor):
        assert extractor._same_document_title("安装指南.pdf", "安装指南")
        assert extractor._same_document_title("# 安装指南", "安装指南")
        assert extractor._same_document_title("安装指南", "其他标题") is False

    def test_is_neighbor_sequence(self, extractor):
        ctx = build_context([ll(1, "1. 甲"), ll(2, "2. 乙")], 1)
        assert extractor._is_neighbor_sequence(2, "ARABIC_SINGLE", ctx)
        ctx2 = build_context([ll(1, "1. 甲"), ll(2, "2. 乙")], 0)
        assert extractor._is_neighbor_sequence(1, "ARABIC_SINGLE", ctx2)


class TestLooksLikePlainHeading:
    def test_too_long(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "长" * 40)], 1)
        assert not extractor._looks_like_plain_heading("长" * 40, ctx)

    def test_sentence_punctuation_end(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "结束。")], 1)
        assert not extractor._looks_like_plain_heading("结束。", ctx)

    def test_url_rejected(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "http://example.com")], 1)
        assert not extractor._looks_like_plain_heading("http://example.com", ctx)

    def test_table_style_rejected(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "|a|")], 1)
        assert not extractor._looks_like_plain_heading("|a|", ctx)

    def test_separator_rejected(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "====")], 1)
        assert not extractor._looks_like_plain_heading("====", ctx)

    def test_not_isolated_rejected(self, extractor):
        ctx = build_context([ll(1, "上"), ll(2, "标题"), ll(3, "下")], 1)
        assert not extractor._looks_like_plain_heading("标题", ctx)

    def test_isolated_with_content_accepted(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "概述"), ll(3, "正文内容")], 1)
        assert extractor._looks_like_plain_heading("概述", ctx)

    def test_chinese_punctuation_rejected(self, extractor):
        ctx = build_context([ll(1, ""), ll(2, "内容，还有")], 1)
        assert not extractor._looks_like_plain_heading("内容，还有", ctx)

    def test_empty_rejected(self, extractor):
        ctx = build_context([ll(1, "")], 0)
        assert not extractor._looks_like_plain_heading("", ctx)


class TestIsRepeatedNoise:
    def test_low_frequency(self, extractor):
        assert not extractor._is_repeated_noise("", "第1页", 1)

    def test_same_as_title(self, extractor):
        assert extractor._is_repeated_noise("标题", "标题", 3)

    def test_copyright(self, extractor):
        assert extractor._is_repeated_noise("", "版权所有 2024 内部资料", 2)

    def test_version_footer_high_frequency(self, extractor):
        assert extractor._is_repeated_noise("", "V1.2 修订说明", 3)

    def test_pipe_line_high_frequency(self, extractor):
        assert extractor._is_repeated_noise("", "页眉 | 页脚", 3)

    def test_plain_repeated_text(self, extractor):
        assert not extractor._is_repeated_noise("", "普通重复行", 3)

    def test_empty_text(self, extractor):
        assert not extractor._is_repeated_noise("", "", 3)
