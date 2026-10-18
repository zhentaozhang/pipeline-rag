"""R1 条件重排 / R2 rank-1 保护 的纯逻辑测试（无网络）。"""

import types

import pytest

import app.rag.engine as engine_module
from app.chat.schema import Evidence
from app.rag.engine import RagRetrievalEngine


def ev(chunk_id, score=0.8, rerank=None):
    kw = {}
    if rerank is not None:
        kw["rerank_score"] = rerank
    return Evidence(
        chunk_id=chunk_id,
        doc_id="d1",
        title="t",
        content=f"c{chunk_id}",
        score=score,
        original_score=score,
        channel="vector",
        **kw,
    )


def settings_with(skip=0.0, guard=False, margin=0.15, enabled=True):
    return types.SimpleNamespace(
        rag=types.SimpleNamespace(
            rerank_skip_min_similarity=skip,
            rerank_rank1_guard_enabled=guard,
            rerank_rank1_guard_margin=margin,
        ),
        rerank=types.SimpleNamespace(enabled=enabled),
    )


class TestRank1Guard:
    def test_restores_when_within_margin(self):
        first = ev("a", rerank=0.90)
        reranked = [ev("b", rerank=0.95), ev("a", rerank=0.90)]
        out = RagRetrievalEngine._apply_rank1_guard([first], reranked, 0.15)
        assert [e.chunk_id for e in out] == ["a", "b"]

    def test_no_restore_when_beyond_margin(self):
        first = ev("a", rerank=0.50)
        reranked = [ev("b", rerank=0.95), ev("a", rerank=0.50)]
        out = RagRetrievalEngine._apply_rank1_guard([first], reranked, 0.15)
        assert [e.chunk_id for e in out] == ["b", "a"]

    def test_noop_when_already_top(self):
        first = ev("a", rerank=0.99)
        reranked = [ev("a", rerank=0.99), ev("b", rerank=0.90)]
        out = RagRetrievalEngine._apply_rank1_guard([first], reranked, 0.15)
        assert [e.chunk_id for e in out] == ["a", "b"]

    def test_noop_when_first_not_present(self):
        first = ev("x", rerank=0.9)
        reranked = [ev("b", rerank=0.95)]
        out = RagRetrievalEngine._apply_rank1_guard([first], reranked, 0.15)
        assert [e.chunk_id for e in out] == ["b"]


class TestConditionalRerank:
    @pytest.mark.asyncio
    async def test_skips_when_top_confidence_high(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", settings_with(skip=0.75))
        called = {"n": 0}

        async def _boom(self, query, evidences):
            called["n"] += 1
            raise AssertionError("reranker should not be called")

        monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _boom)
        candidates = [ev("a", score=0.9), ev("b", score=0.4)]
        notes: list[str] = []
        out = await RagRetrievalEngine()._maybe_rerank("q", candidates, 0, notes, set())
        assert out is candidates
        assert called["n"] == 0
        assert any("跳过重排" in n for n in notes)

    @pytest.mark.asyncio
    async def test_reranks_when_below_threshold(self, monkeypatch):
        monkeypatch.setattr(engine_module, "settings", settings_with(skip=0.95))
        called = {"n": 0}

        async def _fake(self, query, evidences):
            called["n"] += 1
            for i, e in enumerate(evidences):
                e.rerank_score = 1.0 - i * 0.1
            return list(evidences)

        monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _fake)
        candidates = [ev("a", score=0.9), ev("b", score=0.4)]
        out = await RagRetrievalEngine()._maybe_rerank("q", candidates, 0, [], set())
        assert called["n"] == 1
        assert out is not candidates
