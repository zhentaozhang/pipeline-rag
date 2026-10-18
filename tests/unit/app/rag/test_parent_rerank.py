"""父块级重排（实验开关）：让重排看到"最终喂给 LLM 的文本"。

已知问题：现有重排打分的是子块文本，而 LLM 读到的是父块全文。
父块级重排是对齐这两者的最小改动，默认关闭，靠评测判定是否采纳。
"""

from __future__ import annotations

import pytest

from app.chat.schema import Evidence
from app.config import get_settings
from app.rag.engine import RagRetrievalEngine


def _ev(cid: str, text: str) -> Evidence:
    return Evidence(
        chunk_id=cid, doc_id="d1", content=text, title="", source_type="document", score=1.0
    )


@pytest.fixture
def parent_rerank_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings.rag, "parent_rerank_enabled", True, raising=False)
    monkeypatch.setattr(settings.rag, "parent_rerank_top_n", 20, raising=False)
    monkeypatch.setattr(settings.rag, "parent_rerank_max_chars", 40, raising=False)
    monkeypatch.setattr(settings.rerank, "enabled", True, raising=False)
    return settings


async def test_disabled_keeps_order_and_skips_api(monkeypatch):
    engine = RagRetrievalEngine()
    calls: list[int] = []

    async def _boom(*args, **kwargs):  # pragma: no cover - 不应被调用
        calls.append(1)
        raise AssertionError("reranker should not be called when disabled")

    monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _boom)
    parents = [_ev("a", "A 文本"), _ev("b", "B 文本")]
    out = await engine._maybe_rerank_parents("q", parents, 0, [])
    assert [e.chunk_id for e in out] == ["a", "b"]
    assert calls == []


async def test_enabled_reorders_by_parent_text_score(parent_rerank_on, monkeypatch):
    engine = RagRetrievalEngine()

    async def _fake_rerank(self, query, evidences):
        scores = {"a": 0.1, "b": 0.9, "c": 0.5}
        out = []
        for ev in evidences:
            copy = ev.model_copy(update={"rerank_score": scores[ev.chunk_id]})
            out.append(copy)
        return sorted(out, key=lambda e: -e.rerank_score)

    monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _fake_rerank)
    parents = [_ev("a", "A"), _ev("b", "B"), _ev("c", "C")]
    out = await engine._maybe_rerank_parents("q", parents, 0, [])
    assert [e.chunk_id for e in out] == ["b", "c", "a"]


async def test_full_parent_text_is_preserved_after_scoring(parent_rerank_on, monkeypatch):
    engine = RagRetrievalEngine()
    long_text = "父块正文" * 100

    async def _fake_rerank(self, query, evidences):
        # 断言送打分的是截断后的探针文本
        assert all(len(ev.content) <= 40 for ev in evidences)
        return [ev.model_copy(update={"rerank_score": 1.0}) for ev in evidences]

    monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _fake_rerank)
    out = await engine._maybe_rerank_parents("q", [_ev("a", long_text)], 0, [])
    assert out[0].content == long_text
    assert out[0].rerank_score == 1.0


async def test_failure_falls_back_to_original_order(parent_rerank_on, monkeypatch):
    engine = RagRetrievalEngine()

    async def _raise(self, query, evidences):
        raise RuntimeError("rerank api down")

    monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _raise)
    parents = [_ev("a", "A"), _ev("b", "B")]
    notes: list[str] = []
    out = await engine._maybe_rerank_parents("q", parents, 0, notes)
    assert [e.chunk_id for e in out] == ["a", "b"]
    assert any("父块重排" in n for n in notes) or notes == []


async def test_blend_weights_parent_and_child_scores(parent_rerank_on, monkeypatch):
    engine = RagRetrievalEngine()
    monkeypatch.setattr(get_settings().rag, "parent_rerank_blend", 0.5)

    async def _fake_rerank(self, query, evidences):
        # 父块分：a=0.2, b=0.0；子块分（原有 rerank_score）：a=0.0, b=0.4
        scores = {"a": 0.2, "b": 0.0}
        return [ev.model_copy(update={"rerank_score": scores[ev.chunk_id]}) for ev in evidences]

    monkeypatch.setattr("app.rag.reranker.Reranker.rerank", _fake_rerank)
    a = _ev("a", "A")
    b = _ev("b", "B")
    a.rerank_score = 0.0
    b.rerank_score = 0.4
    out = await engine._maybe_rerank_parents("q", [a, b], 0, [])
    # a: 0.5*0.2 + 0.5*0.0 = 0.1 ; b: 0.5*0.0 + 0.5*0.4 = 0.2 → b 在前
    assert [e.chunk_id for e in out] == ["b", "a"]
    assert out[0].rerank_score == pytest.approx(0.2)
