import decimal

import pytest

import app.orchestrator.route_es_repository as repo_module
from app.orchestrator.models import RouteQueryContext
from app.orchestrator.route_es_repository import RouteESRepository


class FakeES:
    def __init__(self, exists=True, hits=None, error=None):
        self._exists = exists
        self._hits = hits or []
        self._error = error
        self.calls = []

    @property
    def indices(self):
        return self

    async def exists(self, **kwargs):
        self.calls.append(("exists", kwargs))
        return self._exists

    async def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        if self._error:
            raise self._error
        return {"hits": {"hits": self._hits}}


class TestSearchLexicalScores:
    @pytest.mark.asyncio
    async def test_empty_text(self, monkeypatch):
        monkeypatch.setattr(repo_module, "get_es", lambda: FakeES())
        assert await RouteESRepository().search_lexical_scores("", "idx", 10) == []

    @pytest.mark.asyncio
    async def test_index_missing(self, monkeypatch):
        es = FakeES(exists=False)
        monkeypatch.setattr(repo_module, "get_es", lambda: es)
        assert await RouteESRepository().search_lexical_scores("q", "idx", 10) == []
        assert es.calls[0][0] == "exists"

    @pytest.mark.asyncio
    async def test_query_shape_and_results(self, monkeypatch):
        es = FakeES(
            hits=[
                {
                    "_source": {"entityCode": "E1", "documentId": "42"},
                    "_score": 1.25,
                },
                {"_source": {"entityCode": "E2"}, "_score": None},
            ]
        )
        monkeypatch.setattr(repo_module, "get_es", lambda: es)
        out = await RouteESRepository().search_lexical_scores("手册", "idx", 5, entity_type="DOC")
        assert out == [
            {"entityCode": "E1", "documentId": "42", "score": 1.25},
            {"entityCode": "E2", "documentId": None, "score": None},
        ]
        search_kw = es.calls[1][1]
        assert search_kw["index"] == "idx"
        assert search_kw["size"] == 5
        body = search_kw["body"]
        assert body["query"]["bool"]["minimum_should_match"] == 1
        assert body["query"]["bool"]["filter"] == [{"term": {"entityType": "DOC"}}]
        should = body["query"]["bool"]["should"]
        assert should[0] == {"term": {"displayName": {"value": "手册", "boost": 2.0}}}

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, monkeypatch):
        es = FakeES(error=RuntimeError("es down"))
        monkeypatch.setattr(repo_module, "get_es", lambda: es)
        assert await RouteESRepository().search_lexical_scores("q", "idx", 5) == []


class FakeRouteService:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error

    async def route_by_query(self, text, tenant_id="default", top_k=5):
        if self.error:
            raise self.error
        return self.results


class TestFallbackEsDocuments:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        es_svc = FakeRouteService(
            results=[
                {
                    "_source": {
                        "documentId": 7,
                        "documentName": "部署手册",
                        "lastIndexTaskId": "task1",
                        "scopeCode": "A",
                        "scopeName": "域A",
                        "businessCategory": "cat",
                        "tags": "tag1",
                    },
                    "_score": 0.12345,
                }
            ]
        )
        monkeypatch.setattr(repo_module, "ElasticsearchKnowledgeRouteIndexService", lambda: es_svc)
        ctx = RouteQueryContext(routing_text="部署", question="部署手册怎么用", rewrite_question="部署手册怎么用", query_terms=["部署"])
        docs = await RouteESRepository().fallback_es_documents(ctx, tenant_id="t1")
        assert len(docs) == 1
        d = docs[0]
        assert d.document_id == "7"
        assert d.document_name == "部署手册"
        assert d.last_index_task_id == "task1"
        assert d.scope_code == "A"
        assert d.business_category == "cat"
        assert d.document_tags == "tag1"
        assert d.score == decimal.Decimal("0.1235")
        assert d.reason == "ES 路由命中"

    @pytest.mark.asyncio
    async def test_uses_routing_text(self, monkeypatch):
        es_svc = FakeRouteService(results=[{"_source": {"documentId": 1}, "_score": 1.0}])
        monkeypatch.setattr(repo_module, "ElasticsearchKnowledgeRouteIndexService", lambda: es_svc)
        ctx = RouteQueryContext(routing_text="路由文本", question="问题", rewrite_question="问题", query_terms=["路由文本"])
        await RouteESRepository().fallback_es_documents(ctx)
        assert es_svc.results is not None

    @pytest.mark.asyncio
    async def test_empty_results(self, monkeypatch):
        monkeypatch.setattr(repo_module, "ElasticsearchKnowledgeRouteIndexService", lambda: FakeRouteService())
        ctx = RouteQueryContext(routing_text="部署", question="q", rewrite_question="q", query_terms=["部署"])
        assert await RouteESRepository().fallback_es_documents(ctx) == []

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            repo_module,
            "ElasticsearchKnowledgeRouteIndexService",
            lambda: FakeRouteService(error=RuntimeError("boom")),
        )
        ctx = RouteQueryContext(routing_text="部署", question="q", rewrite_question="q", query_terms=["部署"])
        assert await RouteESRepository().fallback_es_documents(ctx) == []
