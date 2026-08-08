import types
from decimal import Decimal

from app.chat.memory import MemoryContext
from app.common.enums import ChatQueryMode, ExecutionMode
from app.orchestrator.context import PrepareContext
from app.orchestrator.models import DocumentRouteCandidate, KnowledgeRouteDecision
from app.orchestrator.plan_builder import PlanBuilder


def make_doc(document_id="1", name="部署手册", score="0.9"):
    return DocumentRouteCandidate(
        document_id=document_id,
        document_name=name,
        last_index_task_id="t1",
        scope_code="A",
        scope_name="域A",
        business_category="",
        document_tags="",
        score=Decimal(score),
        reason="r",
    )


def make_ctx(**overrides):
    defaults = dict(
        question="原始问题",
        conversation_id="c1",
        memory_ctx=MemoryContext(),
        chat_mode=ChatQueryMode.AUTO_DOCUMENT,
        tenant_id="t1",
        rewrite_sub_questions=["改写问题"],
        retrieval_sub_questions=["检索问题"],
        retrieval_question="检索问题",
        rewritten_question="改写问题",
        history_summary="历史",
        execution_mode=ExecutionMode.RETRIEVAL,
    )
    defaults.update(overrides)
    return PrepareContext(**defaults)


class TestBuildCommonKwargs:
    def test_common_fields(self):
        ctx = make_ctx()
        kw = PlanBuilder.build_common_kwargs(ctx)
        assert kw["original_question"] == "原始问题"
        assert kw["rewritten_question"] == "改写问题"
        assert kw["retrieval_question"] == "检索问题"
        assert kw["retrieval_sub_questions"] == ["检索问题"]
        assert kw["context_summary"] == "历史"
        assert kw["history_planning_context"] is ctx.history_planning_ctx

    def test_falls_back_to_question(self):
        ctx = make_ctx(rewrite_sub_questions=[], retrieval_sub_questions=[], rewritten_question="", retrieval_question="")
        kw = PlanBuilder.build_common_kwargs(ctx)
        assert kw["rewritten_question"] == "原始问题"
        assert kw["retrieval_sub_questions"] == ["原始问题"]


class TestBuildRefusalPlan:
    def test_mode_and_reply(self):
        plan = PlanBuilder.build_refusal_plan(make_ctx(), "拦截原因")
        assert plan.mode == ExecutionMode.REFUSAL
        assert plan.refusal_reply == "根据企业安全规范，该请求已被拦截：拦截原因"
        assert plan.original_question == "原始问题"


class TestBuildOpenChatPlan:
    def test_mode(self):
        plan = PlanBuilder.build_open_chat_plan(make_ctx())
        assert plan.mode == ExecutionMode.REACT_AGENT
        assert plan.chat_mode == ChatQueryMode.OPEN_CHAT


class TestBuildFinalPlan:
    def test_routed_document_priority(self):
        ctx = make_ctx(
            routed_document_id="routed-id",
            routed_document_name="路由文档",
            routed_task_id="task1",
            top_doc_ids=["d1", "d2"],
            top_task_ids=["task1"],
            retrieval_sub_questions=["Q1", "Q2"],
        )
        plan = PlanBuilder.build_final_plan(ctx)
        assert plan.mode == ExecutionMode.RETRIEVAL
        assert plan.selected_document_id == "routed-id"
        assert plan.selected_document_name == "路由文档"
        assert plan.retrieval_document_ids == ["d1", "d2"]
        assert plan.retrieval_task_ids == ["task1"]
        assert len(plan.sub_questions) == 2
        assert plan.sub_questions[0].text == "Q1"
        assert plan.sub_questions[0].doc_ids == ["d1", "d2"]
        assert plan.sub_questions[0].tenant_id == "t1"

    def test_fallback_to_original_doc_ids(self):
        ctx = make_ctx(
            routed_document_id=None,
            original_doc_ids=["orig1"],
            original_selected_document_id=None,
            original_selected_document_name="原名",
            original_selected_task_id="otask",
        )
        plan = PlanBuilder.build_final_plan(ctx)
        assert plan.selected_document_id == "orig1"
        assert plan.selected_document_name == "原名"
        assert plan.selected_task_id == "otask"

    def test_chat_mode_mapping(self):
        plan = PlanBuilder.build_final_plan(make_ctx(chat_mode=ChatQueryMode.OPEN_CHAT))
        assert plan.chat_mode is None


class TestBuildClarificationReply:
    def test_no_candidates(self):
        reply = PlanBuilder.build_clarification_reply("q", None, [])
        assert "补充更具体的文档名" in reply

    def test_lists_candidates(self):
        docs = [make_doc("1", "手册A"), make_doc("2", "手册B")]
        reply = PlanBuilder.build_clarification_reply("q", None, docs)
        assert "1. 《手册A》" in reply
        assert "2. 《手册B》" in reply

    def test_scope_suffix(self):
        docs = [make_doc("1", "手册A")]
        reply = PlanBuilder.build_clarification_reply("q", None, docs)
        assert "（域A）" in reply


class TestBuildClarificationOptions:
    def test_options(self):
        docs = [make_doc("1", "手册A"), make_doc("2", "手册B"), make_doc("3", "手册C"), make_doc("4", "手册D")]
        out = PlanBuilder.build_clarification_options(docs)
        assert out == ["我想问《手册A》", "我想问《手册B》", "我想问《手册C》"]

    def test_empty(self):
        assert PlanBuilder.build_clarification_options([]) == []


class TestBuildClarificationReason:
    def test_no_decision(self):
        reason = PlanBuilder.build_clarification_reason(None, [])
        assert "没有形成稳定候选" in reason

    def test_with_decision(self):
        decision = KnowledgeRouteDecision(confidence=Decimal("0.35"), documents=[make_doc()])
        reason = PlanBuilder.build_clarification_reason(decision, [make_doc()])
        assert "置信度为 0.35" in reason
        assert "候选文档数为 1" in reason


class TestShouldAskClarification:
    def test_no_candidates(self):
        assert PlanBuilder.should_ask_clarification(None, []) is True

    def test_no_decision(self):
        assert PlanBuilder.should_ask_clarification(None, [make_doc()]) is True

    def test_high_confidence_single_doc(self):
        decision = KnowledgeRouteDecision(confidence=Decimal("0.9"), documents=[make_doc()])
        assert PlanBuilder.should_ask_clarification(decision, [make_doc()]) is False

    def test_low_confidence_asks(self):
        decision = KnowledgeRouteDecision(confidence=Decimal("0.1"), documents=[make_doc()])
        assert PlanBuilder.should_ask_clarification(decision, [make_doc()]) is True

    def test_low_confidence_but_keyword_match(self):
        decision = KnowledgeRouteDecision(confidence=Decimal("0.3"), documents=[make_doc("1", "部署手册")])
        assert PlanBuilder.should_ask_clarification(decision, [make_doc("1", "部署手册")], question="部署手册怎么用") is False

    def test_close_scores_cross_scope_asks(self):
        docs = [make_doc("1", score="0.9"), make_doc("2", score="0.8")]
        docs[1] = types.SimpleNamespace(
            **{**docs[1].__dict__, "scope_code": "B"}
        )
        decision = KnowledgeRouteDecision(confidence=Decimal("0.9"), documents=docs)
        assert PlanBuilder.should_ask_clarification(decision, docs) is True

    def test_same_scope_close_scores_no_ask(self):
        docs = [make_doc("1", score="0.9"), make_doc("2", score="0.8")]
        decision = KnowledgeRouteDecision(confidence=Decimal("0.9"), documents=docs)
        assert PlanBuilder.should_ask_clarification(decision, docs) is False
