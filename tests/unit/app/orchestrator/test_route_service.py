import types
from decimal import Decimal

import pytest

import app.orchestrator.route_service as route_service_module
from app.orchestrator.models import DocumentRouteCandidate, KnowledgeRouteDecision
from app.orchestrator.route_service import KnowledgeRouteService


def make_doc(document_id="5"):
    return DocumentRouteCandidate(
        document_id=document_id,
        document_name="部署手册",
        last_index_task_id="t1",
        scope_code="A",
        scope_name="域A",
        business_category="",
        document_tags="",
        score=Decimal("0.9"),
        reason="r",
    )


class FakeRepo:
    def __init__(self, query_terms=None):
        self.query_terms = query_terms or []
        self.calls = []

    async def build_query_context(self, question, rewrite_question, tokenize):
        self.calls.append(("build", question, rewrite_question))
        return types.SimpleNamespace(query_terms=self.query_terms)

    async def get_ranked_scopes(self, session, ctx, scorer, tenant_id):
        self.calls.append(("scopes", tenant_id))
        return []

    async def get_ranked_topics(self, session, ctx, scopes, scorer, tenant_id):
        self.calls.append(("topics", tenant_id))
        return []

    async def get_ranked_documents(self, session, ctx, scopes, topics, scorer, tenant_id):
        self.calls.append(("docs", tenant_id))
        return []


class FakeScorer:
    def __init__(self):
        self.calls = []

    def tokenize(self, text):
        return ["t"]

    def build_decision(self, scopes, topics, docs):
        self.calls.append(("decision",))
        return KnowledgeRouteDecision(route_status="SUCCESS")


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeTraceStore:
    def __init__(self):
        self.calls = []

    async def save_trace(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class TestRoute:
    @pytest.mark.asyncio
    async def test_no_query_terms_returns_failed(self, monkeypatch):
        repo = FakeRepo(query_terms=[])
        scorer = FakeScorer()
        monkeypatch.setattr(
            route_service_module, "RouteRepository", lambda: repo
        )
        monkeypatch.setattr(route_service_module, "RouteScorer", lambda: scorer)
        svc = KnowledgeRouteService()
        decision = await svc.route("q", "rq")
        assert decision.route_status == "FAILED"
        assert repo.calls == [("build", "q", "rq")]

    @pytest.mark.asyncio
    async def test_full_funnel(self, monkeypatch):
        repo = FakeRepo(query_terms=["t"])
        scorer = FakeScorer()
        monkeypatch.setattr(route_service_module, "RouteRepository", lambda: repo)
        monkeypatch.setattr(route_service_module, "RouteScorer", lambda: scorer)
        monkeypatch.setattr(route_service_module, "AsyncSession", lambda engine: FakeSession())
        monkeypatch.setattr(route_service_module, "get_engine", lambda: "engine")
        svc = KnowledgeRouteService()
        decision = await svc.route("q", "rq", tenant_id="t1")
        assert decision.route_status == "SUCCESS"
        assert repo.calls == [
            ("build", "q", "rq"),
            ("scopes", "t1"),
            ("topics", "t1"),
            ("docs", "t1"),
        ]


class TestRecordShadowRoute:
    @pytest.mark.asyncio
    async def test_records_trace(self, monkeypatch):
        repo = FakeRepo(query_terms=["t"])
        scorer = FakeScorer()
        trace = FakeTraceStore()
        monkeypatch.setattr(route_service_module, "RouteRepository", lambda: repo)
        monkeypatch.setattr(route_service_module, "RouteScorer", lambda: scorer)
        monkeypatch.setattr(route_service_module, "AsyncSession", lambda engine: FakeSession())
        monkeypatch.setattr(route_service_module, "get_engine", lambda: "engine")
        monkeypatch.setattr(route_service_module, "RouteTraceStore", lambda: trace)
        svc = KnowledgeRouteService()
        await svc.record_shadow_route("c1", 1, 5, "q", "rq", tenant_id="t1")
        assert len(trace.calls) == 1
        args, _ = trace.calls[0]
        assert args[5] == "shadow"
        assert args[6].route_status == "SUCCESS"

    @pytest.mark.asyncio
    async def test_error_swallowed(self, monkeypatch):
        class BoomRepo:
            async def build_query_context(self, question, rewrite_question, tokenize):
                raise RuntimeError("repo down")

        monkeypatch.setattr(route_service_module, "RouteRepository", lambda: BoomRepo())
        svc = KnowledgeRouteService()
        await svc.record_shadow_route("c1", 1, None, "q", "rq")


class TestRecordAutoRoute:
    @pytest.mark.asyncio
    async def test_top_document_id(self, monkeypatch):
        trace = FakeTraceStore()
        monkeypatch.setattr(route_service_module, "RouteTraceStore", lambda: trace)
        svc = KnowledgeRouteService()
        decision = KnowledgeRouteDecision(route_status="SUCCESS", documents=[make_doc("42")])
        await svc.record_auto_route("c1", 1, "q", "rq", decision)
        args, _ = trace.calls[0]
        assert args[2] == 42
        assert args[5] == "auto"
        assert args[6] is decision

    @pytest.mark.asyncio
    async def test_no_docs(self, monkeypatch):
        trace = FakeTraceStore()
        monkeypatch.setattr(route_service_module, "RouteTraceStore", lambda: trace)
        svc = KnowledgeRouteService()
        decision = KnowledgeRouteDecision(route_status="FAILED")
        await svc.record_auto_route("c1", 1, "q", "rq", decision)
        assert trace.calls[0][0][2] is None

    @pytest.mark.asyncio
    async def test_error_swallowed(self, monkeypatch):
        class BoomTrace:
            async def save_trace(self, *args, **kwargs):
                raise RuntimeError("trace down")

        monkeypatch.setattr(route_service_module, "RouteTraceStore", lambda: BoomTrace())
        svc = KnowledgeRouteService()
        decision = KnowledgeRouteDecision(route_status="SUCCESS", documents=[make_doc()])
        await svc.record_auto_route("c1", 1, "q", "rq", decision)
