from app.chat.schema import (
    DocumentNavigationDecision,
    ExecutionPlan,
    HistoryPlanningContext,
    ItemAnchor,
    StructureAnchor,
    SubQuestion,
)
from app.common.enums import ExecutionMode
from app.rag.retrieve_request_factory import DocumentRetrieveRequestFactory


def make_plan(sub_questions=None, **overrides):
    defaults = dict(
        mode=ExecutionMode.RAG_CHAT,
        original_question="原始问题",
        rewritten_question="改写问题",
    )
    defaults.update(overrides)
    plan = ExecutionPlan(**defaults)
    plan.sub_questions = sub_questions or []
    return plan


def make_sub_question(index=0, text="问题", **overrides):
    defaults = dict(index=index, text=text)
    defaults.update(overrides)
    return SubQuestion(**defaults)


class TestBuild:
    async def test_empty_sub_questions(self):
        factory = DocumentRetrieveRequestFactory()
        plan = make_plan()
        result = await factory.build(plan)
        assert result is plan

    async def test_blank_sub_question_skipped(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="  ")
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.text == "  "

    async def test_text_overwritten_by_retrieval_query(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置")
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.text.startswith("如何配置")

    async def test_doc_ids_injected_from_plan(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question()
        plan = make_plan([sub], selected_document_id="doc-9")
        await factory.build(plan)
        assert sub.doc_ids == ["doc-9"]

    async def test_doc_ids_not_overwritten(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(doc_ids=["doc-1"])
        plan = make_plan([sub], selected_document_id="doc-9")
        await factory.build(plan)
        assert sub.doc_ids == ["doc-1"]


class TestQueryAugmentation:
    async def test_keyword_hints_appended(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置", query_context_hints=["配置", "部署"])
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.text == "如何配置 配置 部署"

    async def test_keyword_hints_dedup_and_limit(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(
            text="问题内容",
            query_context_hints=["a", "a", "b", "c", "d", "e", "f", "g"],
        )
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.text == "问题内容 a b c d e"

    async def test_augmented_hints_not_written_back(self):
        # 增强后的 query_context_hints 仅用于日志与 text，不写回字段
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="问题内容", query_context_hints=["a", "b"])
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.query_context_hints == ["a", "b"]

    async def test_no_hints_keeps_original(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置数据库")
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.text == "如何配置数据库"

    async def test_meaningful_terms_as_context_hints(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置数据库连接")
        plan = make_plan([sub])
        retrieval_query, hints = factory._build_query_augmentation(
            "如何配置数据库连接", plan, sub.query_context_hints
        )
        assert retrieval_query == "如何配置数据库连接"
        assert hints == ["如何配置数据库连接"]

    async def test_navigation_section_hint(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置")
        nav = DocumentNavigationDecision(
            structure_anchor=StructureAnchor(section_title="第一章 概述")
        )
        plan = make_plan([sub], navigation_decision=nav)
        await factory.build(plan)
        assert "第一章 概述" in sub.text

    async def test_navigation_item_hint(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置")
        nav = DocumentNavigationDecision(item_anchor=ItemAnchor(item_index=3))
        plan = make_plan([sub], navigation_decision=nav)
        await factory.build(plan)
        assert "第3步" in sub.text
        assert "第3项" in sub.text

    async def test_navigation_hints_dedup(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置")
        nav = DocumentNavigationDecision(
            structure_anchor=StructureAnchor(section_title="第一章 概述"),
            item_anchor=ItemAnchor(item_index=1),
        )
        plan = make_plan([sub], navigation_decision=nav)
        await factory.build(plan)
        hints = sub.query_context_hints
        assert len(hints) == len(set(hints))

    async def test_context_hints_capped_at_eight(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="如何配置数据库连接池大小和超时时间", query_context_hints=["a", "b", "c", "d"])
        plan = make_plan([sub])
        await factory.build(plan)
        assert len(sub.query_context_hints) <= 8


class TestShortFollowUp:
    async def test_short_question_uses_history_hints(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="它怎么配置")
        plan = make_plan(
            [sub],
            history_planning_context=HistoryPlanningContext(retrieval_hints=["数据库", "连接"]),
        )
        await factory.build(plan)
        assert "数据库" in sub.text
        assert "连接" in sub.text

    async def test_short_question_without_history(self):
        factory = DocumentRetrieveRequestFactory()
        sub = make_sub_question(text="它呢")
        plan = make_plan([sub])
        await factory.build(plan)
        assert sub.text == "它呢"

    async def test_looks_like_short_follow_up_short(self):
        factory = DocumentRetrieveRequestFactory()
        assert factory._looks_like_short_follow_up("它怎么配置") is True

    async def test_looks_like_short_follow_up_hint(self):
        factory = DocumentRetrieveRequestFactory()
        assert factory._looks_like_short_follow_up("刚才说的方法具体怎么操作") is True
        assert factory._looks_like_short_follow_up("这个参数的含义是什么") is True

    async def test_looks_like_short_follow_up_long(self):
        factory = DocumentRetrieveRequestFactory()
        assert factory._looks_like_short_follow_up("数据库连接池的默认大小如何调整") is False

    async def test_empty_question(self):
        factory = DocumentRetrieveRequestFactory()
        assert factory._looks_like_short_follow_up("") is False
        assert factory._looks_like_short_follow_up(None) is False


class TestBuildFilters:
    async def test_empty_question(self):
        factory = DocumentRetrieveRequestFactory()
        assert factory._build_filters("") == {}
        assert factory._build_filters(None) == {}

    async def test_year_hints(self):
        factory = DocumentRetrieveRequestFactory()
        filters = factory._build_filters("2024 年发布的部署手册")
        assert filters["year_hints"] == ["2024"]

    async def test_section_path_hints(self):
        factory = DocumentRetrieveRequestFactory()
        filters = factory._build_filters("请查看第一章内容")
        assert filters["section_path_hints"] == ["第一章"]

    async def test_appendix_hint(self):
        factory = DocumentRetrieveRequestFactory()
        filters = factory._build_filters("参考附录A")
        assert filters["section_path_hints"] == ["附录A"]

    async def test_document_name_hints(self):
        factory = DocumentRetrieveRequestFactory()
        filters = factory._build_filters("请查看部署手册")
        assert filters["document_name_hints"] == ["部署手册", "手册"]

    async def test_case_insensitive_name_match(self):
        factory = DocumentRetrieveRequestFactory()
        filters = factory._build_filters("FAQ 是什么")
        assert filters["document_name_hints"] == ["FAQ"]

    async def test_plain_question_no_filters(self):
        factory = DocumentRetrieveRequestFactory()
        filters = factory._build_filters("数据库连接池怎么调整")
        assert filters == {
            "document_name_hints": [],
            "business_category_hints": [],
            "document_tag_hints": [],
            "section_path_hints": [],
            "year_hints": [],
        }


class TestExtractMeaningfulTerms:
    async def test_segments_split(self):
        factory = DocumentRetrieveRequestFactory()
        terms = factory._extract_meaningful_terms("配置数据库，调整连接池")
        assert "配置数据库" in terms
        assert "调整连接池" in terms

    async def test_single_char_terms_filtered(self):
        factory = DocumentRetrieveRequestFactory()
        terms = factory._extract_meaningful_terms("配置的数据库")
        assert "的" not in terms

    async def test_dedup(self):
        factory = DocumentRetrieveRequestFactory()
        terms = factory._extract_meaningful_terms("配置配置")
        assert len(terms) == 1

    async def test_capped_at_six(self):
        factory = DocumentRetrieveRequestFactory()
        terms = factory._extract_meaningful_terms(
            "术语一，术语二，术语三，术语四，术语五，术语六，术语七"
        )
        assert len(terms) <= 6

    async def test_empty(self):
        factory = DocumentRetrieveRequestFactory()
        assert factory._extract_meaningful_terms("") == []
        assert factory._extract_meaningful_terms(None) == []
