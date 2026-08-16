import types

import pytest

import app.rag.engine as engine_module
from app.chat.schema import Evidence, ExecutionPlan, SubQuestion, SubQuestionEvidence
from app.common.enums import ExecutionMode
from app.rag.engine import (
    RagRetrievalContext,
    RagRetrievalEngine,
    RetrievalChannelResult,
)


def make_settings(**overrides):
    rag_defaults = dict(
        sub_question_timeout_ms=5000,
        channel_timeout_ms=5000,
        candidate_top_k=10,
        final_top_k=5,
        min_vector_similarity=0.3,
        keyword_channel_enabled=True,
        keyword_score_ratio=0.3,
        rerank_min_score=0.0,
        corrective_retrieval_enabled=False,
        corrective_retrieval_max_rounds=2,
    )
    rag_defaults.update(overrides.get("rag", {}))
    rerank_defaults = dict(enabled=False)
    rerank_defaults.update(overrides.get("rerank", {}))
    return types.SimpleNamespace(
        rag=types.SimpleNamespace(**rag_defaults),
        rerank=types.SimpleNamespace(**rerank_defaults),
    )


def make_evidence(chunk_id="c1", doc_id="d1", **overrides):
    defaults = dict(
        chunk_id=chunk_id,
        doc_id=doc_id,
        title="第一章",
        content="内容",
        score=0.8,
        original_score=0.8,
        channel="vector",
    )
    defaults.update(overrides)
    return Evidence(**defaults)


def make_plan(**overrides):
    defaults = dict(
        mode=ExecutionMode.RAG_CHAT,
        original_question="如何配置数据库",
        rewritten_question="如何配置数据库",
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


class TestRagRetrievalContext:
    def test_is_empty_when_no_evidence_list(self):
        ctx = RagRetrievalContext()
        assert ctx.is_empty is True

    def test_is_empty_when_all_evidence_empty(self):
        ctx = RagRetrievalContext(
            sub_question_evidence_list=[
                SubQuestionEvidence(sub_question=SubQuestion(index=0, text="a"), evidences=[]),
                SubQuestionEvidence(sub_question=SubQuestion(index=0, text="b"), evidences=[]),
            ]
        )
        assert ctx.is_empty is True

    def test_not_empty_when_any_evidence(self):
        ctx = RagRetrievalContext(
            sub_question_evidence_list=[
                SubQuestionEvidence(
                    sub_question=SubQuestion(index=0, text="a"),
                    evidences=[make_evidence()],
                ),
            ]
        )
        assert ctx.is_empty is False


class TestResolveScore:
    def test_original_score_priority(self):
        assert RagRetrievalEngine()._resolve_score(make_evidence(score=0.1, original_score=0.9)) == 0.9

    def test_score_fallback_when_original_zero(self):
        assert RagRetrievalEngine()._resolve_score(make_evidence(original_score=0.0, score=0.5)) == 0.0

    def test_zero_when_both_zero(self):
        assert RagRetrievalEngine()._resolve_score(make_evidence(original_score=0.0, score=0.0)) == 0.0


class TestApplyEvidenceGate:
    def test_vector_filters_below_threshold(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        result = RetrievalChannelResult(
            channel_name="vector",
            documents=[
                make_evidence(chunk_id="a", original_score=0.5),
                make_evidence(chunk_id="b", original_score=0.2),
                make_evidence(chunk_id="c", original_score=0.0),
            ],
        )
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert [e.chunk_id for e in out.documents] == ["a"]
        assert out.documents[0].gate_passed is True
        low = result.documents[1]
        assert low.gate_passed is False

    def test_vector_gate_zero_score_rejected(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        result = RetrievalChannelResult(
            channel_name="vector",
            documents=[make_evidence(chunk_id="a", original_score=0.0)],
        )
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert out.documents == []

    def test_keyword_relative_floor(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        result = RetrievalChannelResult(
            channel_name="keyword",
            documents=[
                make_evidence(chunk_id="a", original_score=6.0),
                make_evidence(chunk_id="b", original_score=1.0),
            ],
        )
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert [e.chunk_id for e in out.documents] == ["a"]

    def test_keyword_floor_zero_keeps_all(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rag=dict(keyword_score_ratio=0.0)))
        result = RetrievalChannelResult(
            channel_name="keyword",
            documents=[
                make_evidence(chunk_id="a", original_score=6.0),
                make_evidence(chunk_id="b", original_score=0.1),
            ],
        )
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert [e.chunk_id for e in out.documents] == ["a", "b"]

    def test_keyword_all_zero_scores_returns_unchanged(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        docs = [make_evidence(chunk_id="a", original_score=0.0)]
        result = RetrievalChannelResult(channel_name="keyword", documents=docs)
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert out.documents == docs

    def test_empty_documents_unchanged(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        result = RetrievalChannelResult(channel_name="vector", documents=[])
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert out.documents == []

    def test_unknown_channel_unchanged(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        docs = [make_evidence(chunk_id="a")]
        result = RetrievalChannelResult(channel_name="web", documents=docs)
        out = RagRetrievalEngine()._apply_evidence_gate(result)
        assert out.documents == docs


class TestApplyRerankFilterAndTopk:
    def test_no_min_score_keeps_all_up_to_topk(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rag=dict(final_top_k=2)))
        docs = [make_evidence(chunk_id=str(i), rerank_score=0.9) for i in range(4)]
        out = RagRetrievalEngine()._apply_rerank_filter_and_topk(docs)
        assert [e.chunk_id for e in out] == ["0", "1"]

    def test_min_rerank_filters_low(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rag=dict(rerank_min_score=0.5, final_top_k=10)))
        docs = [
            make_evidence(chunk_id="a", rerank_score=0.8),
            make_evidence(chunk_id="b", rerank_score=0.3),
        ]
        out = RagRetrievalEngine()._apply_rerank_filter_and_topk(docs)
        assert [e.chunk_id for e in out] == ["a"]

    def test_missing_rerank_score_passes_with_default_one(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rag=dict(rerank_min_score=0.5, final_top_k=10)))
        docs = [make_evidence(chunk_id="a")]  # rerank_score 默认 0.0 -> (e.rerank_score or 1.0)=1.0
        out = RagRetrievalEngine()._apply_rerank_filter_and_topk(docs)
        assert [e.chunk_id for e in out] == ["a"]

    def test_no_rerank_scores_skips_filter(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rag=dict(rerank_min_score=0.9)))
        docs = [make_evidence(chunk_id="a", rerank_score=0.0)]
        out = RagRetrievalEngine()._apply_rerank_filter_and_topk(docs)
        assert [e.chunk_id for e in out] == ["a"]

    def test_all_below_threshold_keeps_top1_not_empty(self, monkeypatch):
        """阈值语义失效（整查询低分区间）时保留最高分 top-1，避免空证据拒答"""
        monkeypatch.setattr(
            engine_module, "settings", make_settings(rag=dict(rerank_min_score=0.35, final_top_k=10))
        )
        docs = [
            make_evidence(chunk_id="high", rerank_score=0.17),
            make_evidence(chunk_id="low", rerank_score=0.06),
        ]
        out = RagRetrievalEngine()._apply_rerank_filter_and_topk(docs)
        assert [e.chunk_id for e in out] == ["high"]


class TestMarkSelection:
    def test_marks_ranks_and_note(self):
        engine = RagRetrievalEngine()
        docs = [make_evidence(chunk_id="a"), make_evidence(chunk_id="b")]
        notes = []
        engine._mark_selection(docs, 1, [], notes)
        assert docs[0].is_selected is True
        assert docs[0].final_rank == 1
        assert docs[0].selection_reason == "已选入最终 Prompt"
        assert docs[1].final_rank == 2
        assert notes == ["子问题1检索完成：，final=2"]


class TestAssignReferenceIds:
    def test_dedup_across_sub_questions(self):
        engine = RagRetrievalEngine()
        se1 = SubQuestionEvidence(
            sub_question=SubQuestion(index=0, text="a"),
            evidences=[make_evidence(chunk_id="c1", doc_id="d1")],
        )
        se2 = SubQuestionEvidence(
            sub_question=SubQuestion(index=0, text="b"),
            evidences=[
                make_evidence(chunk_id="c1", doc_id="d1"),
                make_evidence(chunk_id="c2", doc_id="d1"),
            ],
        )
        engine._assign_reference_ids([se1, se2])
        assert se1.evidences[0].reference_id == 1
        assert se2.evidences[0].reference_id == 1
        assert se2.evidences[1].reference_id == 2


class TestBuildUniqueKey:
    def test_delegates_to_assembly(self):
        ev = make_evidence(chunk_id="c9", doc_id="d9")
        key = RagRetrievalEngine._build_unique_key(ev)
        assert key == RagRetrievalEngine._build_unique_key(ev)
        other = make_evidence(chunk_id="c9", doc_id="d9", title="不同")
        assert RagRetrievalEngine._build_unique_key(other) == key


class TestMarkUsedChannel:
    def test_dedup(self):
        s = set()
        RagRetrievalEngine._mark_used_channel(s, "vector")
        RagRetrievalEngine._mark_used_channel(s, "vector")
        RagRetrievalEngine._mark_used_channel(s, "keyword")
        assert s == {"vector", "keyword"}


class TestMaybeRerank:
    @pytest.mark.asyncio
    async def test_disabled_returns_candidates(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings())
        engine = RagRetrievalEngine()
        docs = [make_evidence(chunk_id="a")]
        assert await engine._maybe_rerank("q", docs, 1, [], set()) == docs

    @pytest.mark.asyncio
    async def test_single_candidate_skipped(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rerank=dict(enabled=True)))
        engine = RagRetrievalEngine()
        docs = [make_evidence(chunk_id="a")]
        assert await engine._maybe_rerank("q", docs, 1, [], set()) == docs

    @pytest.mark.asyncio
    async def test_success_marks_rerank_channel(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rerank=dict(enabled=True)))
        docs = [make_evidence(chunk_id="a"), make_evidence(chunk_id="b")]

        class FakeReranker:
            async def rerank(self, query, candidates):
                return list(reversed(candidates))

        monkeypatch.setattr("app.rag.reranker.Reranker", FakeReranker)
        used = set()
        out = await RagRetrievalEngine()._maybe_rerank("q", docs, 1, [], used)
        assert [e.chunk_id for e in out] == ["b", "a"]
        assert used == {"rerank"}

    @pytest.mark.asyncio
    async def test_exception_falls_back_with_note(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", make_settings(rerank=dict(enabled=True)))
        docs = [make_evidence(chunk_id="a"), make_evidence(chunk_id="b")]

        class BrokenReranker:
            async def rerank(self, query, candidates):
                raise RuntimeError("down")

        monkeypatch.setattr("app.rag.reranker.Reranker", BrokenReranker)
        notes = []
        out = await RagRetrievalEngine()._maybe_rerank("q", docs, 1, notes, set())
        assert out == docs
        assert notes == ["子问题1重排失败，已降级跳过。"]


class TestRewriteQuery:
    @pytest.mark.asyncio
    async def test_empty_question(self):
        assert await RagRetrievalEngine()._rewrite_query("") == ""

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        class FakeRewriteService:
            async def rewrite(self, question, force=False):
                return types.SimpleNamespace(rewritten="改写后的问题")

        monkeypatch.setattr("app.orchestrator.query_rewriter.ChatQueryRewriteService", FakeRewriteService)
        assert await RagRetrievalEngine()._rewrite_query("原问题") == "改写后的问题"

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, monkeypatch):
        class BrokenService:
            async def rewrite(self, question, force=False):
                raise RuntimeError("down")

        monkeypatch.setattr("app.orchestrator.query_rewriter.ChatQueryRewriteService", BrokenService)
        assert await RagRetrievalEngine()._rewrite_query("原问题") == ""


class FakeVectorChannel:
    def __init__(self, docs=None, error=None):
        self.docs = docs or []
        self.error = error

    async def retrieve(self, sub_q):
        if self.error:
            raise self.error
        return self.docs


class FakeElevator:
    async def elevate(self, docs, session=None):
        return docs


@pytest.fixture
def mock_engine_deps(monkeypatch):
    class FakeFactory:
        async def build(self, plan):
            return plan

    def install(vector_docs=None, keyword_docs=None, vector_error=None, keyword_error=None, settings=None):
        monkeypatch.setattr(
            "app.rag.retrieve_request_factory.DocumentRetrieveRequestFactory",
            FakeFactory,
        )
        monkeypatch.setattr(
            "app.rag.channels.vector.VectorRetrievalChannel",
            lambda: FakeVectorChannel(docs=vector_docs, error=vector_error),
        )
        monkeypatch.setattr(
            "app.rag.channels.keyword.KeywordRetrievalChannel",
            lambda: FakeVectorChannel(docs=keyword_docs, error=keyword_error),
        )
        monkeypatch.setattr(engine_module, "ParentBlockElevator", FakeElevator)
        monkeypatch.setattr(
            engine_module,
            "settings",
            settings or make_settings(),
        )
        return RagRetrievalEngine()

    return install


class TestRetrieve:
    @pytest.mark.asyncio
    async def test_success_flow(self, mock_engine_deps):
        engine = mock_engine_deps(
            vector_docs=[make_evidence(chunk_id="v1", original_score=0.9)],
            keyword_docs=[make_evidence(chunk_id="k1", original_score=6.0, channel="keyword")],
        )
        plan = make_plan(retrieval_sub_questions=["子问题A"])
        ctx = await engine.retrieve(plan)
        assert ctx.retrieval_question == "如何配置数据库"
        assert len(ctx.sub_question_evidence_list) == 1
        se = ctx.sub_question_evidence_list[0]
        assert se.sub_question.text == "子问题A"
        assert se.evidences[0].is_selected is True
        assert se.evidences[0].reference_id == 1
        assert se.channel_trace["vector_recalled"] == 1
        assert ctx.used_channels == {"vector", "keyword"}
        assert "子问题1检索完成" in ctx.retrieval_notes[0]

    @pytest.mark.asyncio
    async def test_channel_error_degrades(self, mock_engine_deps):
        engine = mock_engine_deps(
            vector_docs=[make_evidence(chunk_id="v1", original_score=0.9)],
            keyword_error=RuntimeError("es down"),
        )
        plan = make_plan(retrieval_sub_questions=["子问题A"])
        ctx = await engine.retrieve(plan)
        assert len(ctx.sub_question_evidence_list[0].evidences) == 1
        assert any("通道[keyword]检索失败或超时" in n for n in ctx.retrieval_notes)

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_engine_deps):
        engine = mock_engine_deps(vector_docs=[], keyword_docs=[])
        plan = make_plan(retrieval_sub_questions=["子问题A"])
        ctx = await engine.retrieve(plan)
        assert ctx.sub_question_evidence_list[0].evidences == []
        assert ctx.is_empty is True

    @pytest.mark.asyncio
    async def test_retrieval_question_fallback(self, mock_engine_deps):
        engine = mock_engine_deps(vector_docs=[], keyword_docs=[])
        plan = make_plan()
        ctx = await engine.retrieve(plan)
        assert ctx.retrieval_question == "如何配置数据库"

    @pytest.mark.asyncio
    async def test_sub_question_source_plan_sub_questions(self, mock_engine_deps):
        engine = mock_engine_deps(vector_docs=[], keyword_docs=[])
        plan = make_plan(sub_questions=[SubQuestion(index=7, text="计划里的问题")])
        ctx = await engine.retrieve(plan)
        assert ctx.sub_question_evidence_list[0].sub_question.index == 7

    @pytest.mark.asyncio
    async def test_retrieve_one_empty_raw_results(self):
        engine = RagRetrievalEngine()

        async def fake_parallel(*args, **kwargs):
            return []

        engine._parallel_channel_retrieve = fake_parallel
        sub_q = SubQuestion(index=0, text="x")
        se = await engine._retrieve_one(sub_q, 1, make_plan(), set(), [])
        assert se.evidences == []
        assert se.fused_candidate_count == 0


class TestRetrieveWithCorrection:
    @pytest.mark.asyncio
    async def test_disabled_returns_directly(self, mock_engine_deps):
        engine = mock_engine_deps(vector_docs=[make_evidence(chunk_id="v1")])
        plan = make_plan()
        ctx = await engine.retrieve_with_correction(plan)
        assert len(ctx.sub_question_evidence_list) == 1

    @pytest.mark.asyncio
    async def test_enabled_rewrites_when_empty(self, monkeypatch):
        calls = {"rewrite": 0}

        async def fake_rewrite(self, question):
            calls["rewrite"] += 1
            return "改写后"

        monkeypatch.setattr(RagRetrievalEngine, "_rewrite_query", fake_rewrite)

        class FakeFactory:
            async def build(self, plan):
                return plan

        class AlwaysEmptyVector:
            async def retrieve(self, sub_q):
                return []

        class SecondRoundVector:
            def __init__(self):
                self.round = 0

            async def retrieve(self, sub_q):
                self.round += 1
                if self.round >= 2:
                    return [make_evidence(chunk_id="v1")]
                return []

        class FakeElevator2:
            async def elevate(self, docs, session=None):
                return docs

        monkeypatch.setattr("app.rag.retrieve_request_factory.DocumentRetrieveRequestFactory", FakeFactory)
        monkeypatch.setattr(
            engine_module,
            "settings",
            make_settings(rag=dict(corrective_retrieval_enabled=True)),
        )
        monkeypatch.setattr(engine_module, "ParentBlockElevator", FakeElevator2)
        channel = SecondRoundVector()
        monkeypatch.setattr("app.rag.channels.vector.VectorRetrievalChannel", lambda: channel)
        monkeypatch.setattr("app.rag.channels.keyword.KeywordRetrievalChannel", lambda: AlwaysEmptyVector())

        engine = RagRetrievalEngine()
        plan = make_plan()
        ctx = await engine.retrieve_with_correction(plan)
        assert calls["rewrite"] == 1
        assert not ctx.is_empty
        assert any("已按改写查询重查" in n for n in ctx.retrieval_notes)
