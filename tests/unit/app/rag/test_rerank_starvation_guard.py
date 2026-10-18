"""D3：重排阈值饥饿不变量（阈值不得把证据集砍到 final_top_k 以下）。"""

from app.chat.schema import Evidence
from app.config import get_settings
from app.rag.engine import RagRetrievalEngine


def make_ev(i: int, score: float) -> Evidence:
    return Evidence(
        chunk_id=f"c{i}",
        doc_id="d1",
        title="文档",
        content="内容",
        source_type="document",
        rerank_score=score,
    )


def _set(monkeypatch, *, abs_min: float, ratio: float, final_k: int, guard: bool) -> None:
    r = get_settings().rag
    monkeypatch.setattr(r, "rerank_min_score", abs_min)
    monkeypatch.setattr(r, "rerank_relative_ratio", ratio)
    monkeypatch.setattr(r, "final_top_k", final_k)
    monkeypatch.setattr(r, "rerank_filter_starvation_guard_enabled", guard)


class TestRerankStarvationGuard:
    def test_guard_skips_filter_when_starved(self, monkeypatch):
        _set(monkeypatch, abs_min=0.35, ratio=0.0, final_k=8, guard=True)
        docs = [make_ev(0, 0.9), make_ev(1, 0.8)] + [make_ev(i, 0.01) for i in range(2, 10)]
        out = RagRetrievalEngine()._apply_rerank_filter(docs)
        # 阈值只留 2 条 < final_top_k=8 → 跳过阈值，保留全部候选
        assert out == docs

    def test_filter_applies_when_depth_is_met(self, monkeypatch):
        _set(monkeypatch, abs_min=0.35, ratio=0.0, final_k=8, guard=True)
        docs = [make_ev(i, 0.9) for i in range(8)] + [make_ev(i, 0.01) for i in range(8, 10)]
        out = RagRetrievalEngine()._apply_rerank_filter(docs)
        assert out == docs[:8]

    def test_guard_disabled_keeps_old_behavior(self, monkeypatch):
        _set(monkeypatch, abs_min=0.35, ratio=0.0, final_k=8, guard=False)
        docs = [make_ev(0, 0.9), make_ev(1, 0.8)] + [make_ev(i, 0.01) for i in range(2, 10)]
        out = RagRetrievalEngine()._apply_rerank_filter(docs)
        assert out == docs[:2]

    def test_no_threshold_returns_all(self, monkeypatch):
        _set(monkeypatch, abs_min=0.0, ratio=0.0, final_k=8, guard=True)
        docs = [make_ev(i, 0.01) for i in range(10)]
        out = RagRetrievalEngine()._apply_rerank_filter(docs)
        assert out == docs

    def test_unscored_docs_pass_through(self, monkeypatch):
        _set(monkeypatch, abs_min=0.35, ratio=0.0, final_k=8, guard=True)
        docs = [
            Evidence(
                chunk_id="c1",
                doc_id="d1",
                title="文档",
                content="内容",
                source_type="document",
            ),
        ]
        out = RagRetrievalEngine()._apply_rerank_filter(docs)
        assert out == docs

    def test_relative_ratio_starvation_also_guarded(self, monkeypatch):
        _set(monkeypatch, abs_min=0.0, ratio=0.35, final_k=8, guard=True)
        # top=0.98 → 0.343；只有 1 条过线
        docs = [make_ev(0, 0.98)] + [make_ev(i, 0.001) for i in range(1, 10)]
        out = RagRetrievalEngine()._apply_rerank_filter(docs)
        assert out == docs


class TestDefault:
    def test_guard_default_on(self):
        assert get_settings().rag.rerank_filter_starvation_guard_enabled is True
