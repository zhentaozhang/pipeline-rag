import types
from decimal import Decimal

import pytest

from app.orchestrator.knowledge_router import route, route_by_document
from app.orchestrator.models import DocumentRouteCandidate, KnowledgeRouteDecision


def make_doc(document_id="1", name="部署手册", scope_code="A", score="0.9"):
    return DocumentRouteCandidate(
        document_id=document_id,
        document_name=name,
        last_index_task_id="t1",
        scope_code=scope_code,
        scope_name="",
        business_category="",
        document_tags="",
        score=Decimal(score),
        reason="r",
    )


class FakeRouteService:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error
        self.route_calls = []
        self.auto_calls = []

    async def route(self, question, rewrite_question, tenant_id="default"):
        self.route_calls.append((question, rewrite_question))
        if self.error:
            raise self.error
        return self.decision

    async def record_auto_route(self, *args, **kwargs):
        self.auto_calls.append(args)


class TestRoute:
    @pytest.mark.asyncio
    async def test_no_candidates_react_agent(self, monkeypatch):
        svc = FakeRouteService(decision=KnowledgeRouteDecision(route_status="FAILED"))
        monkeypatch.setattr(
            "app.orchestrator.route_service.KnowledgeRouteService", lambda: svc
        )
        decision = await route("q")
        assert decision.execution_mode == "REACT_AGENT"
        assert svc.auto_calls == []

    @pytest.mark.asyncio
    async def test_single_doc_retrieval(self, monkeypatch):
        svc = FakeRouteService(
            decision=KnowledgeRouteDecision(route_status="SUCCESS", documents=[make_doc("7")])
        )
        monkeypatch.setattr(
            "app.orchestrator.route_service.KnowledgeRouteService", lambda: svc
        )
        decision = await route("q", "rq", conversation_id="c1", exchange_id=3)
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.doc_ids == ["7"]
        assert svc.auto_calls[0][:4] == ("c1", 3, "q", "rq")
        assert svc.auto_calls[0][4] is svc.decision

    @pytest.mark.asyncio
    async def test_close_scores_cross_scope_clarification(self, monkeypatch):
        svc = FakeRouteService(
            decision=KnowledgeRouteDecision(
                route_status="SUCCESS",
                documents=[make_doc("1", "手册A", scope_code="A", score="0.9"), make_doc("2", "手册B", scope_code="B", score="0.8")],
            )
        )
        monkeypatch.setattr(
            "app.orchestrator.route_service.KnowledgeRouteService", lambda: svc
        )
        decision = await route("q")
        assert decision.execution_mode == "CLARIFICATION"
        assert decision.clarification_options == [
            "我想问《手册A》",
            "我想问《手册B》",
        ]
        assert "文档范围歧义" in decision.clarification_reply

    @pytest.mark.asyncio
    async def test_same_scope_no_clarification(self, monkeypatch):
        svc = FakeRouteService(
            decision=KnowledgeRouteDecision(
                route_status="SUCCESS",
                documents=[make_doc("1", "手册A", scope_code="A", score="0.9"), make_doc("2", "手册B", scope_code="A", score="0.8")],
            )
        )
        monkeypatch.setattr(
            "app.orchestrator.route_service.KnowledgeRouteService", lambda: svc
        )
        decision = await route("q")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.doc_ids == ["1"]

    @pytest.mark.asyncio
    async def test_service_error_propagates(self, monkeypatch):
        svc = FakeRouteService(error=RuntimeError("down"))
        monkeypatch.setattr(
            "app.orchestrator.route_service.KnowledgeRouteService", lambda: svc
        )
        with pytest.raises(RuntimeError):
            await route("q")


class FakeNavDecision:
    def __init__(self, action=None, item_anchor=None):
        self.action = action
        self.item_anchor = item_anchor


class TestRouteByDocument:
    @pytest.mark.asyncio
    async def test_no_document_id(self):
        decision = await route_by_document(None, "q")
        assert decision.execution_mode == "RETRIEVAL"

    @pytest.mark.asyncio
    async def test_nav_none(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer.analyze", FakeAsyncNone())
        decision = await route_by_document("1", "q")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.doc_ids == ["1"]

    @pytest.mark.asyncio
    async def test_section_lookup_graph_only(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer.analyze",
            FakeAsyncDecision(FakeNavDecision(action="SECTION_ADJACENCY_LOOKUP")),
        )
        decision = await route_by_document("1", "q")
        assert decision.execution_mode == "GRAPH_ONLY"

    @pytest.mark.asyncio
    async def test_item_reference_graph_then_evidence(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer.analyze",
            FakeAsyncDecision(
                FakeNavDecision(action="ITEM_REFERENCE", item_anchor=types.SimpleNamespace(item_index=2))
            ),
        )
        decision = await route_by_document("1", "q")
        assert decision.execution_mode == "GRAPH_THEN_EVIDENCE"

    @pytest.mark.asyncio
    async def test_item_reference_without_index_retrieval(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.navigation_analyzer.analyze",
            FakeAsyncDecision(FakeNavDecision(action="ITEM_REFERENCE", item_anchor=None)),
        )
        decision = await route_by_document("1", "q")
        assert decision.execution_mode == "RETRIEVAL"
        assert decision.doc_ids == ["1"]


class FakeAsyncNone:
    async def __call__(self, **kwargs):
        return None


class FakeAsyncDecision:
    def __init__(self, result):
        self.result = result

    async def __call__(self, **kwargs):
        return self.result
