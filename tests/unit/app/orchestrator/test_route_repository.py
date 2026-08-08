from decimal import Decimal

import pytest

from app.db.models.document import Document, DocumentProfile
from app.db.models.knowledge import KnowledgeScope, KnowledgeTopic, TopicDocumentRelation
from app.orchestrator.models import (
    DocumentRouteCandidate,
    RouteQueryContext,
    ScopeRouteCandidate,
    TopicRouteCandidate,
)
from app.orchestrator.route_repository import RouteRepository
from app.orchestrator.route_scorer import RouteScorer


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, scopes=None, topics=None, documents=None, profiles=None, relations=None):
        self.scopes = scopes or []
        self.topics = topics or []
        self.documents = documents or []
        self.profiles = profiles or []
        self.relations = relations or []

    async def execute(self, stmt):
        sql = str(stmt)
        if "pipeline_rag_knowledge_scope_node" in sql:
            return FakeResult(self.scopes)
        if "pipeline_rag_knowledge_topic_node" in sql:
            return FakeResult(self.topics)
        if "pipeline_rag_document_profile" in sql:
            return FakeResult(self.profiles)
        if "pipeline_rag_topic_document_relation" in sql:
            return FakeResult(self.relations)
        if "pipeline_rag_document" in sql:
            return FakeResult(self.documents)
        raise AssertionError(f"unexpected select: {sql[:80]}")


class FakeProvider:
    def __init__(self, vectors):
        self.vectors = vectors
        self.batches = []

    async def embed_batch(self, texts):
        self.batches.append(texts)
        return self.vectors[: len(texts)]


class FakeES:
    def __init__(self, lexical=None, fallback=None):
        self.lexical = lexical or []
        self.fallback = fallback or []
        self.calls = []

    async def search_lexical_scores(self, routing_text, index_name, size, entity_type=""):
        self.calls.append((routing_text, index_name, size, entity_type))
        return self.lexical

    async def fallback_es_documents(self, ctx, tenant_id):
        return self.fallback


def make_doc(doc_id, name, scope_code="ops", tags="安装,部署", index_status=3, task_id="t1"):
    return Document(
        id=doc_id,
        tenant_id="default",
        doc_id=f"d{doc_id}",
        document_name=name,
        original_file_name=f"{name}.pdf",
        file_type=1,
        index_status=index_status,
        knowledge_scope_code=scope_code,
        knowledge_scope_name="运维域",
        document_tags=tags,
        last_index_task_id=task_id,
    )


def make_profile(doc_id, summary="摘要", topics='["配置","故障"]', questions='["如何配置"]'):
    return DocumentProfile(
        id=doc_id,
        document_id=doc_id,
        profile_status=2,
        status=1,
        document_summary=summary,
        core_topics=topics,
        example_questions=questions,
    )


def make_ctx(query_embedding=None):
    return RouteQueryContext(
        question="如何配置",
        rewrite_question="",
        routing_text="如何配置",
        query_terms=["配置"],
        query_embedding=query_embedding,
    )


@pytest.fixture
def repo(monkeypatch):
    def fake_get_provider():
        return FakeProvider([])

    monkeypatch.setattr("app.orchestrator.route_repository.get_embedding_provider", fake_get_provider)
    return RouteRepository()


class TestBuildRoutingText:
    def test_both(self, repo):
        assert repo._build_routing_text("原问题", "改写问题") == "原问题 改写问题"

    def test_only_original(self, repo):
        assert repo._build_routing_text("原问题", "") == "原问题"

    def test_only_rewritten(self, repo):
        assert repo._build_routing_text("", "改写问题") == "改写问题"

    def test_same_dedup(self, repo):
        assert repo._build_routing_text("原问题", "原问题") == "原问题"

    def test_strips(self, repo):
        assert repo._build_routing_text(" 原问题 ", " ") == "原问题"


class TestParseJsonArray:
    def test_valid_array(self, repo):
        assert repo._parse_json_array('["a", " b ", ""]') == ["a", "b"]

    def test_empty_raw(self, repo):
        assert repo._parse_json_array("") == []
        assert repo._parse_json_array("[]") == []

    def test_invalid_json(self, repo):
        assert repo._parse_json_array("{broken") == []

    def test_not_a_list(self, repo):
        assert repo._parse_json_array('"just a string"') == []

    def test_none(self, repo):
        assert repo._parse_json_array(None) == []


class TestComputeSemanticScores:
    async def _repo_with(self, repo, vectors):
        repo.embedding_provider = FakeProvider(vectors)
        return repo

    @pytest.mark.asyncio
    async def test_no_embedding_all_zero(self, repo):
        repo.embedding_provider = FakeProvider([])
        ctx = make_ctx(query_embedding=None)
        scores = await repo._compute_semantic_scores(ctx, ["a", "b"], RouteScorer())
        assert scores == [0.0, 0.0]

    @pytest.mark.asyncio
    async def test_empty_route_texts(self, repo):
        repo.embedding_provider = FakeProvider([])
        scores = await repo._compute_semantic_scores(make_ctx([1.0]), [], RouteScorer())
        assert scores == []

    @pytest.mark.asyncio
    async def test_provider_error_all_zero(self, repo):
        class BoomProvider:
            async def embed_batch(self, texts):
                raise RuntimeError("boom")

        repo.embedding_provider = BoomProvider()
        scores = await repo._compute_semantic_scores(make_ctx([1.0]), ["a"], RouteScorer())
        assert scores == [0.0]

    @pytest.mark.asyncio
    async def test_batched_cosine(self, repo):
        vectors = [[1.0, 0.0], [0.0, 1.0], [0.707, 0.707]]
        repo.embedding_provider = FakeProvider(vectors)
        scores = await repo._compute_semantic_scores(
            make_ctx([1.0, 0.0]), ["a", "b", "c"], RouteScorer()
        )
        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(0.0)
        assert scores[2] == pytest.approx(0.707, abs=1e-3)

    @pytest.mark.asyncio
    async def test_zero_embedding_skips(self, repo):
        repo.embedding_provider = FakeProvider([])
        scores = await repo._compute_semantic_scores(make_ctx(None), ["a"], RouteScorer())
        assert scores == [0.0]


class TestBuildQueryContext:
    @pytest.mark.asyncio
    async def test_with_tokenize_fn(self, repo):
        repo.embedding_provider = FakeProvider([[1.0]])
        ctx = await repo.build_query_context("如何配置", "如何配置日志", tokenize_fn=lambda t: ["配置"])
        assert ctx.question == "如何配置"
        assert ctx.rewrite_question == "如何配置日志"
        assert ctx.routing_text == "如何配置 如何配置日志"
        assert ctx.query_terms == ["配置"]
        assert ctx.query_embedding == [1.0]

    @pytest.mark.asyncio
    async def test_embedding_error_keeps_context(self, repo):
        class BoomProvider:
            async def embed_batch(self, texts):
                raise RuntimeError("boom")

        repo.embedding_provider = BoomProvider()
        ctx = await repo.build_query_context("如何配置", "")
        assert ctx.query_embedding is None
        assert ctx.routing_text == "如何配置"


class TestGetRankedScopes:
    @pytest.mark.asyncio
    async def test_empty_scopes_derives_from_documents(self, repo):
        repo.embedding_provider = FakeProvider([])
        repo.es_repo = FakeES()
        session = FakeSession(documents=[make_doc(1, "安装文档")])
        candidates = await repo.get_ranked_scopes(session, make_ctx(None), RouteScorer())
        assert candidates == []

    @pytest.mark.asyncio
    async def test_derived_scope_from_documents(self, repo):
        repo.embedding_provider = FakeProvider([[1.0, 0.0]])
        repo.es_repo = FakeES()
        session = FakeSession(
            documents=[
                make_doc(1, "安装文档", scope_code="ops", tags="安装,部署"),
                make_doc(2, "排障文档", scope_code="ops", tags="故障,排查"),
            ]
        )
        candidates = await repo.get_ranked_scopes(
            session, make_ctx([1.0, 0.0]), RouteScorer()
        )
        assert len(candidates) == 1
        assert candidates[0].scope_code == "ops"
        assert candidates[0].score > 0

    @pytest.mark.asyncio
    async def test_ranks_and_truncates_to_5(self, repo):
        vectors = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3], [0.6, 0.4], [0.5, 0.5]]
        repo.embedding_provider = FakeProvider(vectors)
        repo.es_repo = FakeES()
        session = FakeSession(
            scopes=[
                KnowledgeScope(scope_code=f"s{i}", scope_name=f"域{i}", description="d")
                for i in range(6)
            ]
        )
        candidates = await repo.get_ranked_scopes(session, make_ctx([1.0, 0.0]), RouteScorer())
        assert len(candidates) == 5
        assert candidates[0].scope_code == "s0"

    @pytest.mark.asyncio
    async def test_lexical_hits_add_score(self, repo):
        repo.embedding_provider = FakeProvider([[0.0, 0.0], [0.0, 0.0]])
        repo.es_repo = FakeES(lexical=[{"entityCode": "s1", "score": 3.0}])
        session = FakeSession(
            scopes=[
                KnowledgeScope(scope_code="s0", scope_name="域0", description=""),
                KnowledgeScope(scope_code="s1", scope_name="域1", description=""),
            ]
        )
        candidates = await repo.get_ranked_scopes(session, make_ctx([1.0, 0.0]), RouteScorer())
        assert {c.scope_code: c.score for c in candidates}["s1"] > 0
        assert "s0" not in {c.scope_code for c in candidates}

    @pytest.mark.asyncio
    async def test_zero_scores_filtered(self, repo):
        repo.embedding_provider = FakeProvider([[0.0, 0.0]])
        repo.es_repo = FakeES()
        session = FakeSession(
            scopes=[KnowledgeScope(scope_code="s1", scope_name="域1", description="")]
        )
        candidates = await repo.get_ranked_scopes(session, make_ctx([1.0, 0.0]), RouteScorer())
        assert candidates == []


class TestGetRankedTopics:
    @pytest.mark.asyncio
    async def test_empty_topics_derives_from_profiles(self, repo):
        repo.embedding_provider = FakeProvider([])
        repo.es_repo = FakeES()
        session = FakeSession(profiles=[])
        candidates = await repo.get_ranked_topics(
            session, make_ctx(None), [], RouteScorer()
        )
        assert candidates == []

    @pytest.mark.asyncio
    async def test_derived_topics_from_profiles(self, repo):
        repo.embedding_provider = FakeProvider([[1.0, 0.0]])
        repo.es_repo = FakeES()
        session = FakeSession(
            documents=[make_doc(1, "安装文档", scope_code="ops")],
            profiles=[make_profile(1, topics='["安装部署"]')],
        )
        candidates = await repo.get_ranked_topics(
            session, make_ctx([1.0, 0.0]), [ScopeRouteCandidate("ops", "运维", Decimal("1.0"), "")], RouteScorer()
        )
        assert len(candidates) == 1
        assert candidates[0].topic_name == "安装部署"
        assert candidates[0].score > 0

    @pytest.mark.asyncio
    async def test_preferred_scope_boost(self, repo):
        vectors = [[0.0, 0.0], [0.0, 0.0]]
        repo.embedding_provider = FakeProvider(vectors)
        repo.es_repo = FakeES()
        session = FakeSession(
            topics=[
                KnowledgeTopic(topic_code="t1", topic_name="主题甲", scope_code="ops"),
                KnowledgeTopic(topic_code="t2", topic_name="主题乙", scope_code="fin"),
            ]
        )
        scope_candidates = [ScopeRouteCandidate("ops", "运维", Decimal("1.0"), "")]
        candidates = await repo.get_ranked_topics(
            session, make_ctx([1.0, 0.0]), scope_candidates, RouteScorer()
        )
        by_code = {c.topic_code: c.score for c in candidates}
        assert by_code["t1"] - by_code["t2"] == Decimal("8.0")

    @pytest.mark.asyncio
    async def test_truncates_to_8(self, repo):
        vectors = [[1.0, 0.0]] * 10
        repo.embedding_provider = FakeProvider(vectors)
        repo.es_repo = FakeES()
        session = FakeSession(
            topics=[KnowledgeTopic(topic_code=f"t{i}", topic_name=f"主题{i}") for i in range(10)]
        )
        candidates = await repo.get_ranked_topics(
            session, make_ctx([1.0, 0.0]), set(), RouteScorer()
        )
        assert len(candidates) == 8


class TestGetRankedDocuments:
    @pytest.mark.asyncio
    async def test_no_documents_es_fallback(self, repo):
        repo.embedding_provider = FakeProvider([])
        fallback = [DocumentRouteCandidate("1", "回退文档", "", "ops", "", "", "", Decimal("0"), "")]
        repo.es_repo = FakeES(fallback=fallback)
        candidates = await repo.get_ranked_documents(
            FakeSession(), make_ctx(None), [], [], RouteScorer()
        )
        assert candidates == fallback

    @pytest.mark.asyncio
    async def test_top_scope_boost(self, repo):
        repo.embedding_provider = FakeProvider([[0.0, 0.0], [0.0, 0.0]])
        repo.es_repo = FakeES()
        session = FakeSession(
            documents=[
                make_doc(1, "安装文档", scope_code="ops"),
                make_doc(2, "财务文档", scope_code="fin"),
            ],
            profiles=[make_profile(1), make_profile(2)],
            relations=[],
        )
        scope = ScopeRouteCandidate("ops", "运维", Decimal("1.0"), "")
        candidates = await repo.get_ranked_documents(
            session, make_ctx([1.0, 0.0]), [scope], [], RouteScorer()
        )
        by_id = {c.document_id: c.score for c in candidates}
        assert by_id["1"] - by_id["2"] == Decimal("15.0")

    @pytest.mark.asyncio
    async def test_relation_score_boost(self, repo):
        repo.embedding_provider = FakeProvider([[0.0, 0.0], [0.0, 0.0]])
        repo.es_repo = FakeES()
        session = FakeSession(
            documents=[make_doc(1, "安装文档", scope_code="ops")],
            profiles=[make_profile(1, topics='["无关主题"]', questions='["无关问题"]')],
            relations=[TopicDocumentRelation(topic_code="t1", document_id=1, relation_score=Decimal("0.5"))],
        )
        topic = TopicRouteCandidate("t1", "主题甲", "ops", Decimal("1.0"), "")
        candidates = await repo.get_ranked_documents(
            session, make_ctx([1.0, 0.0]), [], [topic], RouteScorer()
        )
        assert candidates[0].document_id == "1"
        assert candidates[0].score == Decimal("10.0")

    @pytest.mark.asyncio
    async def test_zero_score_goes_es_fallback(self, repo):
        repo.embedding_provider = FakeProvider([[0.0, 0.0]])
        fallback = [DocumentRouteCandidate("9", "回退文档", "", "", "", "", "", Decimal("0"), "")]
        repo.es_repo = FakeES(fallback=fallback)
        session = FakeSession(
            documents=[make_doc(1, "完全无关文档", scope_code="ops")],
            profiles=[make_profile(1, summary="", topics='["无关"]', questions='["无关"]')],
        )
        candidates = await repo.get_ranked_documents(
            session, make_ctx(None), [], [], RouteScorer()
        )
        assert candidates == fallback

    @pytest.mark.asyncio
    async def test_filtered_empty_es_fallback(self, repo):
        repo.embedding_provider = FakeProvider([[0.0, 0.0]])
        fallback = [DocumentRouteCandidate("9", "回退文档", "", "", "", "", "", Decimal("0"), "")]
        repo.es_repo = FakeES(fallback=fallback)
        session = FakeSession(
            documents=[make_doc(1, "完全无关文档", scope_code="ops")],
            profiles=[make_profile(1, summary="", topics='["无关"]', questions='["无关"]')],
        )
        candidates = await repo.get_ranked_documents(
            session, make_ctx(None), [], [], RouteScorer()
        )
        assert candidates == fallback

    @pytest.mark.asyncio
    async def test_truncates_to_5(self, repo):
        vectors = [[0.9, 0.1]] * 6
        repo.embedding_provider = FakeProvider(vectors)
        repo.es_repo = FakeES()
        session = FakeSession(
            documents=[make_doc(i, f"文档{i}") for i in range(6)],
            profiles=[make_profile(i) for i in range(6)],
            relations=[],
        )
        candidates = await repo.get_ranked_documents(
            session, make_ctx([1.0, 0.0]), [], [], RouteScorer()
        )
        assert len(candidates) == 5
