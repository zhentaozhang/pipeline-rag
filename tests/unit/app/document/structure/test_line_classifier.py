
from app.document.structure.line_classifier import DocumentLineClassifier

C = DocumentLineClassifier


class TestClassifyBasics:
    def test_empty_line_is_body(self):
        assert C.classify("").kind == "BODY"
        assert C.classify("   ").kind == "BODY"

    def test_none_is_body(self):
        assert C.classify(None).kind == "BODY"

    def test_plain_text_is_body(self):
        r = C.classify("这是一段普通正文内容")
        assert r.kind == "BODY"
        assert r.title == "这是一段普通正文内容"
        assert r.level == 0


class TestMarkdownHeading:
    def test_h1(self):
        r = C.classify("# 一级标题")
        assert r.kind == "HEADING"
        assert r.level == 1
        assert r.title == "一级标题"

    def test_h2(self):
        r = C.classify("## 二级标题")
        assert r.level == 2

    def test_h6(self):
        r = C.classify("###### 六级标题")
        assert r.level == 6

    def test_title_stripped(self):
        r = C.classify("###   带空格标题   ")
        assert r.title == "带空格标题"


class TestAppendix:
    def test_appendix_letter(self):
        r = C.classify("附录A")
        assert r.kind == "HEADING"
        assert r.level == 1

    def test_appendix_with_content(self):
        r = C.classify("附录B 补充材料")
        assert r.kind == "HEADING"
        assert r.level == 1


class TestExplicitStep:
    def test_chinese_step(self):
        r = C.classify("第1步 初始化环境")
        assert r.kind == "LIST_ITEM"

    def test_chinese_numeral_step(self):
        r = C.classify("第二步 配置参数")
        assert r.kind == "LIST_ITEM"

    def test_step_prefix_style(self):
        r = C.classify("步骤3 检查状态")
        assert r.kind == "LIST_ITEM"


class TestChapter:
    def test_chapter(self):
        r = C.classify("第一章 概述")
        assert r.kind == "HEADING"
        assert r.level == 2

    def test_article(self):
        r = C.classify("第二条 定义")
        assert r.kind == "HEADING"
        assert r.level == 2


class TestDecimalHeading:
    def test_two_level(self):
        r = C.classify("1.1 安装部署")
        assert r.kind == "HEADING"
        assert r.level == 2

    def test_three_level(self):
        r = C.classify("1.2.3 详细配置")
        assert r.kind == "HEADING"
        assert r.level == 3

    def test_with_delimiter(self):
        r = C.classify("2.3、常见问题")
        assert r.kind == "HEADING"
        assert r.level == 2


class TestChineseOutline:
    def test_heading_like_content(self):
        r = C.classify("一、概述")
        assert r.kind == "HEADING"
        assert r.level == 1

    def test_long_content_is_list(self):
        r = C.classify("一、" + "长" * 25)
        assert r.kind == "LIST_ITEM"

    def test_punctuated_short_content_is_list(self):
        r = C.classify("一、" + "内" * 10 + "，还有")
        assert r.kind == "LIST_ITEM"

    def test_punctuated_content_is_list(self):
        r = C.classify("一、先做第一步，然后继续")
        assert r.kind == "LIST_ITEM"

    def test_sentence_end_is_list(self):
        r = C.classify("一、内容到此结束。")
        assert r.kind == "LIST_ITEM"

    def test_hundreds_outline(self):
        r = C.classify("十、收尾工作")
        assert r.kind == "HEADING"


class TestSingleLevelDigit:
    def test_heading_like(self):
        r = C.classify("1. 概述")
        assert r.kind == "HEADING"
        assert r.level == 1

    def test_long_content_is_list(self):
        r = C.classify("1. " + "长" * 25)
        assert r.kind == "LIST_ITEM"


class TestBullets:
    def test_dash_bullet(self):
        r = C.classify("- 条目一")
        assert r.kind == "LIST_ITEM"

    def test_star_bullet(self):
        r = C.classify("* 条目二")
        assert r.kind == "LIST_ITEM"

    def test_plus_bullet(self):
        r = C.classify("+ 条目三")
        assert r.kind == "LIST_ITEM"

    def test_checkbox(self):
        r = C.classify("- [x] 已完成任务")
        assert r.kind == "LIST_ITEM"
        r = C.classify("* [ ] 待办任务")
        assert r.kind == "LIST_ITEM"


class TestLooksLikeHeadingContent:
    def test_empty_false(self):
        assert not C._looks_like_heading_content("")
        assert not C._looks_like_heading_content("   ")

    def test_sentence_punctuation_false(self):
        assert not C._looks_like_heading_content("结束。")
        assert not C._looks_like_heading_content("结束！")
        assert not C._looks_like_heading_content("结束?")
        assert not C._looks_like_heading_content("结束;")

    def test_too_long_false(self):
        assert not C._looks_like_heading_content("长" * 25)

    def test_chinese_punctuation_false(self):
        assert not C._looks_like_heading_content("内容，还有")
        assert not C._looks_like_heading_content("内容；还有")
        assert not C._looks_like_heading_content("内容：还有")
        assert not C._looks_like_heading_content("内容。还有")

    def test_valid_true(self):
        assert C._looks_like_heading_content("安装部署指南")
        assert C._looks_like_heading_content("概述")

    def test_boundary_24_chars(self):
        assert C._looks_like_heading_content("长" * 24)
        assert not C._looks_like_heading_content("长" * 25)


class TestHeadingAndListItemHelpers:
    def test_heading_clamps_level(self):
        r = C.heading(0, "标题", "标题")
        assert r.level == 1
        r = C.heading(-2, "标题", "标题")
        assert r.level == 1

    def test_heading_strips(self):
        r = C.heading(2, "  标题  ", "  标题  ")
        assert r.title == "标题"
        assert r.raw_text == "标题"

    def test_list_item(self):
        r = C.list_item("  - 条目  ")
        assert r.kind == "LIST_ITEM"
        assert r.title == "- 条目"
        assert r.level == 0

    def test_is_heading(self):
        assert C.classify("# 标题").is_heading()
        assert not C.classify("正文").is_heading()


class TestOrderingPrecedence:
    def test_step_beats_chapter_pattern(self):
        r = C.classify("第一步 初始化")
        assert r.kind == "LIST_ITEM"

    def test_decimal_beats_single_digit(self):
        r = C.classify("1.2 节")
        assert r.level == 2

    def test_single_digit_without_dot_is_body(self):
        r = C.classify("1 纯数字行")
        assert r.kind == "BODY"

    def test_markdown_wins_over_all(self):
        r = C.classify("# 1.1 混合格式")
        assert r.level == 1
