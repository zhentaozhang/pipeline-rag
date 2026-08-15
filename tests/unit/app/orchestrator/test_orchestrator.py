import types
from decimal import Decimal

import pytest

import app.orchestrator.orchestrator as orchestrator_module
from app.chat.memory import MemoryContext
from app.chat.schema import DocumentNavigationDecision
from app.common.enums import ChatQueryMode
from app.orchestrator.models import DocumentRouteCandidate, KnowledgeRouteDecision


def make_doc(document_id="7", name="部署手册", score="0.9", task_id="t1"):
    return DocumentRouteCandidate(
        document_id=document_id,
        document_name=name,
        last_index_task_id=task_id,
        scope_code="A",
        scope_name="域A",
        business_category="",
        document_tags="",
        score=Decimal(score),
        reason="r",
    )


def make_settings():
    return types.SimpleNamespace(
        rag=types.SimpleNamespace(
            enabled=True,
            no_evidence_reply="未找到相关文档",
            planning_history_max_chars=2000,
            answer_history_max_chars=1500,
            knowledge_route_confidence_threshold=0.4,
        ),
        safety=types.SimpleNamespace(mode="monitor"),
    )


class FakeGuardrailService:
    def __init__(self, is_safe=True, reason=""):
        self.is_safe = is_safe
        self.reason = reason

    async def evaluate(self, question):
        return (self.is_safe, self.reason)


class FakeRewriteService:
    def __init__(self, rewritten=None, sub_questions=None, intent="knowledge"):
        self.rewritten = rewritten
        self.sub_questions = sub_questions
        self.intent = intent

    async def rewrite(self, **kwargs):
        return types.SimpleNamespace(
            rewritten=self.rewritten,
            sub_questions=self.sub_questions,
            needs_rewrite=self.rewritten is not None,
            intent=self.intent,
        )


class FakeAssembler:
    def _assemble_answer_history(self, question, transcript):
        return types.SimpleNamespace(
            rendered_text="ah",
            structured_context="",
            recent_context="rc",
            follow_up_question=False,
            total_budget=100,
            recent_budget=50,
            structured_budget=50,
        )


class FakeRouteService:
    def __init__(self, decision):
        self.decision = decision
        self.route_calls = []
        self.auto_calls = []
        self.shadow_calls = []

    async def route(self, question, rewrite_question, tenant_id="default"):
        self.route_calls.append((question, rewrite_question))
        return self.decision

    async def record_auto_route(self, *args):
        self.auto_calls.append(args)

    async def record_shadow_route(self, *args):
        self.shadow_calls.append(args)


class FakeSupervisor:
    async def decompose(self, plan):
        return plan


class FakeNavResult(DocumentNavigationDecision):
    pass


class FakeFallbackRouter:
    candidates = []

    @staticmethod
    async def select_auto_candidates(route_decision, question, rewrite_question):
        return FakeFallbackRouter.candidates


def install_fakes(
    monkeypatch,
    *,
    guardrail=None,
    rewrite=None,
    route=None,
    nav=None,
    settings=None,
    fallback_docs=None,
):
    monkeypatch.setattr(
        "app.orchestrator.stages.guardrails.IntentGuardrailService",
        lambda: guardrail if guardrail is not None else FakeGuardrailService(),
    )
    monkeypatch.setattr(
        "app.orchestrator.stages.query_rewrite.ChatQueryRewriteService",
        lambda: rewrite if rewrite is not None else FakeRewriteService(rewritten="改写后问题"),
    )
    monkeypatch.setattr(
        "app.orchestrator.history_builder.ChatQueryRewriteService",
        lambda: FakeAssembler(),
    )
    route_svc = route if route is not None else FakeRouteService(
        KnowledgeRouteDecision(
            route_status="SUCCESS",
            confidence=Decimal("0.9"),
            documents=[make_doc()],
        )
    )
    monkeypatch.setattr(
        "app.orchestrator.stages.knowledge_routing.KnowledgeRouteService",
        lambda: route_svc,
    )
    monkeypatch.setattr(
        "app.orchestrator.stages.navigation_analysis.nav_analyze",
        FakeNav(nav_result=nav),
    )
    monkeypatch.setattr(
        "app.orchestrator.stages.knowledge_routing.FallbackRouter",
        FakeFallbackRouter,
    )
    FakeFallbackRouter.candidates = (
        fallback_docs
        if fallback_docs is not None
        else (route_svc.decision.documents if route_svc.decision else [])
    )
    monkeypatch.setattr("app.orchestrator.orchestrator.SupervisorService", lambda: FakeSupervisor())
    settings = settings if settings is not None else make_settings()
    for module in (
        "app.orchestrator.plan_builder",
        "app.orchestrator.stages.validation",
        "app.orchestrator.stages.knowledge_routing",
        "app.orchestrator.fallback_router",
    ):
        monkeypatch.setattr(module + ".get_settings", lambda: settings)
    return route_svc


class FakeNav:
    def __init__(self, nav_result=None):
        self.nav_result = nav_result

    async def __call__(self, **kwargs):
        return self.nav_result


class TestPrepare:
    @pytest.mark.asyncio
    async def test_chat_mode_none_raises(self):
        with pytest.raises(ValueError):
            await orchestrator_module.prepare(
                "q", "c1", MemoryContext(), chat_mode=None
            )


class TestAutoDocumentFlow:
    @pytest.mark.asyncio
    async def test_full_retrieval_flow(self, monkeypatch):
        route_svc = install_fakes(monkeypatch)
        plan = await orchestrator_module.prepare("部署手册怎么用", "c1", MemoryContext())
        assert plan.mode.value == "RETRIEVAL"
        assert plan.selected_document_id == "7"
        assert plan.selected_document_name == "部署手册"
        assert plan.selected_task_id == "t1"
        assert plan.retrieval_document_ids == ["7"]
        assert plan.original_question == "部署手册怎么用"
        assert plan.sub_questions[0].text == "改写后问题"
        assert plan.sub_questions[0].doc_ids == ["7"]
        assert plan.sub_questions[0].tenant_id == "default"
        assert route_svc.auto_calls and route_svc.auto_calls[0][3] == "改写后问题"
        assert plan.is_time_sensitive is False

    @pytest.mark.asyncio
    async def test_intent_open_redirects(self, monkeypatch):
        install_fakes(monkeypatch, rewrite=FakeRewriteService(rewritten="改写后问题", intent="open"))
        plan = await orchestrator_module.prepare("聊聊生活", "c1", MemoryContext())
        assert plan.mode.value == "REACT_AGENT"
        assert plan.chat_mode == ChatQueryMode.OPEN_CHAT

    @pytest.mark.asyncio
    async def test_low_confidence_clarification(self, monkeypatch):
        route_svc = FakeRouteService(
            KnowledgeRouteDecision(
                route_status="LOW_CONFIDENCE",
                confidence=Decimal("0.1"),
                documents=[make_doc("3", "手册三", score="0.2")],
            )
        )
        install_fakes(
            monkeypatch,
            route=route_svc,
            fallback_docs=[make_doc("3", "手册三", score="0.2")],
        )
        plan = await orchestrator_module.prepare("想查哪个文档", "c1", MemoryContext())
        assert plan.mode.value == "CLARIFICATION"
        assert "《手册三》" in plan.clarification_reply
        assert plan.clarification_options
        assert "置信度" in plan.clarification_reason

    @pytest.mark.asyncio
    async def test_guardrail_block_refusal(self, monkeypatch):
        install_fakes(monkeypatch, guardrail=FakeGuardrailService(is_safe=False, reason="越权"))
        plan = await orchestrator_module.prepare("询问薪资", "c1", MemoryContext())
        assert plan.mode.value == "REFUSAL"
        assert "越权" in plan.refusal_reply

    @pytest.mark.asyncio
    async def test_open_chat_shortcut(self, monkeypatch):
        install_fakes(monkeypatch)
        plan = await orchestrator_module.prepare("随便聊聊", "c1", MemoryContext(), chat_mode="open_chat")
        assert plan.mode.value == "REACT_AGENT"
        assert plan.chat_mode == ChatQueryMode.OPEN_CHAT

    @pytest.mark.asyncio
    async def test_document_mode_shadow_route(self, monkeypatch):
        route_svc = FakeRouteService(
            KnowledgeRouteDecision(route_status="SUCCESS", confidence=Decimal("0.9"), documents=[make_doc("5")])
        )
        install_fakes(monkeypatch, route=route_svc)
        plan = await orchestrator_module.prepare(
            "文档里的配置", "c1", MemoryContext(), doc_ids=["5"], chat_mode="document"
        )
        assert plan.mode.value == "RETRIEVAL"
        assert plan.selected_document_id == "5"
        assert len(route_svc.shadow_calls) == 1
        assert route_svc.shadow_calls[0][2] == 5
        assert route_svc.auto_calls == []

    @pytest.mark.asyncio
    async def test_document_mode_missing_doc_ids_raises(self, monkeypatch):
        install_fakes(monkeypatch)
        with pytest.raises(ValueError):
            await orchestrator_module.prepare("文档里的配置", "c1", MemoryContext(), chat_mode="document")

    @pytest.mark.asyncio
    async def test_navigation_mode_flows_through(self, monkeypatch):
        install_fakes(
            monkeypatch,
            nav=FakeNavResult(execution_mode="GRAPH_ONLY"),
            fallback_docs=[make_doc()],
        )
        plan = await orchestrator_module.prepare("章节导航", "c1", MemoryContext())
        assert plan.mode.value == "GRAPH_ONLY"
        assert plan.navigation_decision is not None
        assert plan.retrieval_question == "改写后问题"
