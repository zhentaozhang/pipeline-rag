import json
import types
from decimal import Decimal

from app.orchestrator.models import (
    KnowledgeRouteDecision,
    ScopeRouteCandidate,
    TopicRouteCandidate,
)
from app.orchestrator.route_trace_store import (
    ROUTE_STATUS_FAILED,
    ROUTE_STATUS_LOW_CONFIDENCE,
    ROUTE_STATUS_SUCCESS,
    RouteTraceStore,
)


def make_doc(document_id="1", document_name="手册", score="0.9"):
    return types.SimpleNamespace(
        document_id=document_id, document_name=document_name, score=Decimal(score), reason="r"
    )


def make_scope(scope_code="A"):
    return ScopeRouteCandidate(
        scope_code=scope_code, scope_name="域A", score=Decimal("0.8"), reason="s"
    )


def make_topic(topic_code="T1"):
    return TopicRouteCandidate(
        topic_code=topic_code,
        topic_name="主题1",
        scope_code="A",
        score=Decimal("0.7"),
        reason="t",
    )


class TestJsonWriters:
    def test_scope_json(self):
        out = json.loads(RouteTraceStore()._write_scope_json([make_scope()]))
        assert out[0] == {
            "scopeCode": "A",
            "scopeName": "域A",
            "score": "0.8",
            "reason": "s",
        }

    def test_topic_json(self):
        out = json.loads(RouteTraceStore()._write_topic_json([make_topic()]))
        assert out[0]["topicCode"] == "T1"
        assert out[0]["scopeCode"] == "A"

    def test_document_json(self):
        out = json.loads(RouteTraceStore()._write_document_json([make_doc()]))
        assert out[0]["documentId"] == "1"
        assert out[0]["documentName"] == "手册"

    def test_empty(self):
        assert RouteTraceStore()._write_scope_json([]) == "[]"


class TestResolveRouteStatus:
    def test_none_failed(self):
        assert RouteTraceStore()._resolve_route_status(None) == ROUTE_STATUS_FAILED

    def test_success(self):
        assert (
            RouteTraceStore()._resolve_route_status(
                KnowledgeRouteDecision(route_status="SUCCESS")
            )
            == ROUTE_STATUS_SUCCESS
        )

    def test_low_confidence(self):
        assert (
            RouteTraceStore()._resolve_route_status(
                KnowledgeRouteDecision(route_status="LOW_CONFIDENCE")
            )
            == ROUTE_STATUS_LOW_CONFIDENCE
        )

    def test_unknown_failed(self):
        assert (
            RouteTraceStore()._resolve_route_status(
                KnowledgeRouteDecision(route_status="OTHER")
            )
            == ROUTE_STATUS_FAILED
        )


class TestResolveHitSelectedDocument:
    def test_no_selected(self):
        store = RouteTraceStore()
        decision = KnowledgeRouteDecision(route_status="SUCCESS")
        assert store._resolve_hit_selected_document(None, decision) is None

    def test_hit_in_top3(self):
        store = RouteTraceStore()
        decision = KnowledgeRouteDecision(
            route_status="SUCCESS", documents=[make_doc("1"), make_doc("2"), make_doc("3"), make_doc("4")]
        )
        assert store._resolve_hit_selected_document(3, decision) == 1

    def test_miss_outside_top3(self):
        store = RouteTraceStore()
        decision = KnowledgeRouteDecision(
            route_status="SUCCESS", documents=[make_doc("1"), make_doc("2"), make_doc("3")]
        )
        assert store._resolve_hit_selected_document(4, decision) == 0

    def test_no_documents(self):
        store = RouteTraceStore()
        decision = KnowledgeRouteDecision(route_status="SUCCESS")
        assert store._resolve_hit_selected_document(1, decision) is None
