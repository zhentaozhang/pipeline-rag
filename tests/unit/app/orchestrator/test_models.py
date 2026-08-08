from decimal import Decimal

from app.orchestrator.models import (
    DocumentRouteCandidate,
    KnowledgeRouteDecision,
    RouteQueryContext,
    ScopeRouteCandidate,
)


def make_doc(document_id="1", **overrides):
    defaults = dict(
        document_id=document_id,
        document_name="手册",
        last_index_task_id="t1",
        scope_code="A",
        scope_name="域A",
        business_category="cat",
        document_tags="tag",
        score=Decimal("0.9"),
        reason="r",
    )
    defaults.update(overrides)
    return DocumentRouteCandidate(**defaults)


class TestRouteQueryContext:
    def test_defaults(self):
        ctx = RouteQueryContext(question="q", rewrite_question="r", routing_text="t", query_terms=["a"])
        assert ctx.query_embedding is None


class TestKnowledgeRouteDecision:
    def test_defaults(self):
        d = KnowledgeRouteDecision()
        assert d.scopes == []
        assert d.documents == []
        assert d.confidence == Decimal("0.0")
        assert d.route_status == "FAILED"

    def test_top_document(self):
        d = KnowledgeRouteDecision(documents=[make_doc(), make_doc("2")])
        assert d.top_document().document_id == "1"

    def test_top_document_empty(self):
        assert KnowledgeRouteDecision().top_document() is None

    def test_scopes_and_topics(self):
        d = KnowledgeRouteDecision(
            scopes=[ScopeRouteCandidate(scope_code="A", scope_name="域", score=Decimal("1"), reason="r")],
        )
        assert d.scopes[0].scope_code == "A"
