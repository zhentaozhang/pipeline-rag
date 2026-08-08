import pytest

from app.orchestrator.knowledge_router import route_by_document
from app.orchestrator.navigation_analyzer import (
    RetrievalQuestionPlan,
    RewriteResult,
    _asks_adjacency,
    _asks_item_lookup,
    _asks_outline,
    _build_query_hints,
    _detect_facet,
    _looks_analytic_question,
    _mentions_structure,
    _normalize_sub_questions,
    _parse_chinese_number,
    _resolve_by_section_code,
    analyze,
)


class TestParseChineseNumber:
    def test_arabic_digits(self):
        assert _parse_chinese_number("5") == 5
        assert _parse_chinese_number("12") == 12

    def test_single_chinese_digit(self):
        assert _parse_chinese_number("三") == 3

    def test_ten(self):
        assert _parse_chinese_number("十") == 10

    def test_ten_plus(self):
        assert _parse_chinese_number("十一") == 11
        assert _parse_chinese_number("十五") == 15

    def test_multiple_of_ten(self):
        assert _parse_chinese_number("二十") == 20
        assert _parse_chinese_number("九十") == 90

    def test_composite(self):
        assert _parse_chinese_number("二十一") == 21
        assert _parse_chinese_number("三十二") == 32

    def test_invalid(self):
        assert _parse_chinese_number("abc") is None
        assert _parse_chinese_number("") is None
        assert _parse_chinese_number("零") is None


class TestHintDetection:
    def test_adjacency_hits(self):
        assert _asks_adjacency("上一节是什么")
        assert _asks_adjacency("帮我看看下一节内容")

    def test_adjacency_miss(self):
        assert not _asks_adjacency("这个步骤怎么操作")

    def test_outline_hits(self):
        assert _asks_outline("文档包含哪些章节")
        assert _asks_outline("看一下目录")

    def test_outline_miss(self):
        assert not _asks_outline("这一步怎么走")

    def test_item_lookup_hits(self):
        assert _asks_item_lookup("具体步骤是什么")
        assert _asks_item_lookup("第几步最重要")

    def test_analytic_hits(self):
        assert _looks_analytic_question("为什么会出现这个结果")
        assert _looks_analytic_question("两个方案的区别是什么")

    def test_analytic_miss(self):
        assert not _looks_analytic_question("第二步做什么")

    def test_mentions_structure_hits(self):
        assert _mentions_structure("这个章节讲什么")
        assert _mentions_structure('找到"安装部署"这一节')
        assert _mentions_structure("1.2.3 小节")

    def test_mentions_structure_miss(self):
        assert not _mentions_structure("今天天气怎么样")


class TestResolveSectionCode:
    def test_matches_dotted_code(self):
        assert _resolve_by_section_code("1.2.3 是什么", "") == {
            "code": "1.2.3",
            "title": "1.2.3",
        }

    def test_matches_from_rewritten(self):
        assert _resolve_by_section_code("", "如何理解 3.4") == {
            "code": "3.4",
            "title": "3.4",
        }

    def test_no_code(self):
        assert _resolve_by_section_code("这个章节讲什么", "") is None


class TestNormalizeSubQuestions:
    def test_none_falls_back(self):
        assert _normalize_sub_questions(None, "fallback") == ["fallback"]

    def test_empty_list_falls_back(self):
        assert _normalize_sub_questions(RewriteResult(sub_questions=[]), "fb") == ["fb"]

    def test_strips_and_drops_empty(self):
        result = _normalize_sub_questions(
            RewriteResult(sub_questions=[" a ", "", "  b"]), "fb"
        )
        assert result == ["a", "b"]

    def test_deduplicates(self):
        result = _normalize_sub_questions(
            RewriteResult(sub_questions=["a", "a", "b"]), "fb"
        )
        assert result == ["a", "b"]

    def test_dict_style_sub_questions(self):
        class Fake:
            sub_questions = ["x", "y"]

        assert _normalize_sub_questions(Fake(), "fb") == ["x", "y"]

    def test_all_empty_falls_back(self):
        assert _normalize_sub_questions(RewriteResult(sub_questions=["", "  "]), "fb") == ["fb"]


class TestBuildQueryHints:
    def test_splits_retrieval_question(self):
        plan = RetrievalQuestionPlan("配置 权限、隔离及运维", [])
        hints = _build_query_hints(plan, None, None)
        assert "配置" in hints
        assert "权限" in hints
        assert "隔离" in hints
        assert "运维" in hints

    def test_drops_short_segments(self):
        plan = RetrievalQuestionPlan("a b cd", [])
        hints = _build_query_hints(plan, None, None)
        assert hints == ["cd"]

    def test_section_title_and_code(self):
        plan = RetrievalQuestionPlan("q", [])
        hints = _build_query_hints(plan, {"title": "安装部署", "code": "1.2"}, None)
        assert "安装部署" in hints
        assert "1.2" in hints

    def test_item_hints(self):
        plan = RetrievalQuestionPlan("q", [])
        hints = _build_query_hints(plan, None, 2)
        assert "第2步" in hints
        assert "第2项" in hints

    def test_deduplicates(self):
        plan = RetrievalQuestionPlan("安装 安装 部署", [])
        hints = _build_query_hints(plan, None, None)
        assert hints == ["安装", "部署"]

    def test_capped_at_10(self):
        plan = RetrievalQuestionPlan("甲甲 乙乙 丙丙 丁丁 戊戊 己己 庚庚 辛辛 壬壬 癸癸 子子 丑丑", [])
        hints = _build_query_hints(plan, None, None)
        assert len(hints) == 10


class TestDetectFacet:
    def test_adjacency_facet(self):
        assert _detect_facet("上一节是什么") == "章节位置"

    def test_outline_facet(self):
        assert _detect_facet("包含哪些章节") == "章节"

    def test_item_facet(self):
        assert _detect_facet("具体步骤是什么") == "步骤"

    def test_default(self):
        assert _detect_facet("随便问问") == ""


class TestAnalyze:
    @pytest.mark.asyncio
    async def test_plain_question_goes_retrieval(self):
        decision = await analyze(None, "如何配置日志")
        assert decision is not None
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.action == "FRESH_TOPIC"
        assert decision.structure_anchor.scope_mode == "NONE"

    @pytest.mark.asyncio
    async def test_section_code_question_retrieval_with_soft_hint(self):
        decision = await analyze(None, "1.2.3 讲了什么")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.action == "FRESH_TOPIC"

    @pytest.mark.asyncio
    async def test_adjacency_question_goes_graph_only(self):
        decision = await analyze(None, "上一节是什么")
        assert decision.execution_mode == "GRAPH_ONLY"
        assert decision.action == "SECTION_ADJACENCY_LOOKUP"
        assert decision.structure_anchor.scope_mode == "GRAPH_UNRESOLVED"

    @pytest.mark.asyncio
    async def test_outline_question_goes_graph_only(self):
        decision = await analyze(None, "这个文档包含哪些章节")
        assert decision.execution_mode == "GRAPH_ONLY"
        assert decision.action == "CHILD_SECTION_DESCEND"

    @pytest.mark.asyncio
    async def test_analytic_overrides_structure_hint(self):
        decision = await analyze(None, "为什么目录顺序是这样")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.action == "FRESH_TOPIC"

    @pytest.mark.asyncio
    async def test_step_question_item_reference(self):
        decision = await analyze(None, "第二步怎么操作")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.action == "ITEM_REFERENCE"
        assert decision.item_anchor is not None
        assert decision.item_anchor.item_index == 2

    @pytest.mark.asyncio
    async def test_chinese_step_numeral_normalized(self):
        decision = await analyze(None, "第五步怎么做")
        assert decision.item_anchor is not None
        assert decision.item_anchor.item_index == 5

    @pytest.mark.asyncio
    async def test_rewrite_result_preferred(self):
        rewrite = RewriteResult(
            rewritten_question="问题甲", sub_questions=["问题甲", "问题乙"]
        )
        decision = await analyze(None, "原始", rewrite)
        assert decision.query_context_hints == ["问题甲"]
        assert decision.execution_mode == "RETRIEVAL"

    @pytest.mark.asyncio
    async def test_multiple_sub_questions_block_graph_only(self):
        rewrite = RewriteResult(
            rewritten_question="上一节是什么", sub_questions=["上一节是什么", "下一节是什么"]
        )
        decision = await analyze(None, "上一节是什么", rewrite)
        assert decision.execution_mode == "RETRIEVAL"

    @pytest.mark.asyncio
    async def test_rewritten_attribute_supported(self):
        class FakeRewrite:
            rewritten = "使用 rewritten 字段"
            sub_questions = None

        decision = await analyze(None, "原始", FakeRewrite())
        assert decision.execution_mode == "RETRIEVAL"


class TestRouteByDocument:
    @pytest.mark.asyncio
    async def test_no_document_id_goes_retrieval(self):
        decision = await route_by_document(None, "如何配置")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.doc_ids == []

    @pytest.mark.asyncio
    async def test_adjacency_question_graph_only(self, monkeypatch):
        async def fake_resolve(doc_id, original, rewritten):
            return None

        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer._resolve_section", fake_resolve
        )
        decision = await route_by_document("doc1", "上一节是什么")
        assert decision is not None
        assert decision.execution_mode == "GRAPH_ONLY"
        assert decision.doc_ids == ["doc1"]

    @pytest.mark.asyncio
    async def test_step_question_graph_then_evidence(self, monkeypatch):
        async def fake_resolve(doc_id, original, rewritten):
            return {
                "id": "sec1",
                "code": "1.1",
                "title": "安装",
                "path": "1.1",
                "contentText": "第一步 初始化。第二步 配置。",
            }

        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer._resolve_section", fake_resolve
        )
        decision = await route_by_document("doc1", "第二步做什么")
        assert decision is not None
        assert decision.execution_mode == "GRAPH_THEN_EVIDENCE"
        assert decision.doc_ids == ["doc1"]

    @pytest.mark.asyncio
    async def test_plain_question_retrieval(self, monkeypatch):
        async def fake_resolve(doc_id, original, rewritten):
            return None

        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer._resolve_section", fake_resolve
        )
        decision = await route_by_document("doc1", "如何配置")
        assert decision is not None
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.doc_ids == ["doc1"]
