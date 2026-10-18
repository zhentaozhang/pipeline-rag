"""证据 ID 序列必须与文本序列同序（Task 1：chunk 级召回判定依赖它）。"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.evaluation.runner import (
    _extract_context_ids,
    _extract_context_parent_ids,
    _extract_context_texts,
)


def _ev(chunk_id, parent_block_id, content, rerank_score=0.0, score=0.0, ref=1):
    return SimpleNamespace(
        chunk_id=chunk_id,
        parent_block_id=parent_block_id,
        content=content,
        rerank_score=rerank_score,
        score=score,
        reference_id=ref,
    )


def _ctx(*groups):
    return SimpleNamespace(
        sub_question_evidence_list=[SimpleNamespace(evidences=list(group)) for group in groups]
    )


class TestContextIdExtraction:
    def test_ids_follow_rerank_order(self):
        ctx = _ctx(
            [
                _ev("c1", 10, "低分片段", rerank_score=0.1),
                _ev("c2", 11, "高分片段", rerank_score=0.9),
            ]
        )
        assert _extract_context_ids(ctx) == ["c2", "c1"]
        assert _extract_context_texts(ctx)[0].endswith("高分片段")

    def test_dedup_by_chunk_id(self):
        ctx = _ctx([_ev("c1", 10, "片段A", rerank_score=0.5)], [_ev("c1", 10, "片段A", 0.5)])
        assert _extract_context_ids(ctx) == ["c1"]

    def test_blank_chunk_id_is_skipped_but_parent_kept(self):
        ctx = _ctx([_ev(None, 10, "无ID片段", 0.5)])
        assert _extract_context_ids(ctx) == []
        assert _extract_context_parent_ids(ctx) == ["10"]
        assert len(_extract_context_texts(ctx)) == 1

    def test_parent_ids_align_with_retrieval_order(self):
        ctx = _ctx(
            [
                _ev("c1", 10, "片段A", rerank_score=0.2),
                _ev("c2", 11, "片段B", rerank_score=0.8),
            ]
        )
        assert _extract_context_parent_ids(ctx) == ["11", "10"]

    def test_missing_parent_block_id_skipped(self):
        ctx = _ctx([_ev("c1", None, "片段", 0.5)])
        assert _extract_context_parent_ids(ctx) == []

    def test_fallback_sort_uses_score_when_no_rerank(self):
        ctx = _ctx(
            [
                _ev("c1", 10, "A", rerank_score=0.0, score=0.3),
                _ev("c2", 11, "B", rerank_score=0.0, score=0.7),
            ]
        )
        assert _extract_context_ids(ctx) == ["c2", "c1"]


class TestApplyIdMetrics:
    def _pair(self, chunk_ids=("c1", "c2"), parent_ids=("p1",)):
        from types import SimpleNamespace

        result = SimpleNamespace(
            retrieved_chunk_ids=list(chunk_ids),
            retrieved_parent_ids=list(parent_ids),
        )
        question = SimpleNamespace(relevant_chunk_ids=[], relevant_parent_ids=[])
        return result, question

    def test_uses_grounded_gold_ids(self):
        from scripts.evaluation.runner import _apply_id_metrics

        result, question = self._pair()
        _apply_id_metrics(
            result,
            question,
            {"relevant_chunk_ids": ["c2"], "relevant_parent_ids": ["p1"]},
            8,
        )
        assert result.recall_at_5_ids == 1.0
        assert result.mrr_ids == 0.5
        assert result.recall_at_5_parent_ids == 1.0

    def test_explicit_question_gold_takes_precedence(self):
        from scripts.evaluation.runner import _apply_id_metrics

        result, question = self._pair()
        question.relevant_chunk_ids = ["c1"]
        _apply_id_metrics(
            result,
            question,
            {"relevant_chunk_ids": ["c2"], "relevant_parent_ids": []},
            8,
        )
        assert result.recall_at_5_ids == 1.0
        assert result.mrr_ids == 1.0

    def test_no_gold_leaves_metrics_none(self):
        from scripts.evaluation.runner import _apply_id_metrics

        result, question = self._pair()
        _apply_id_metrics(result, question, {}, 8)
        assert result.recall_at_5_ids is None
        assert result.mrr_ids is None
        assert result.recall_at_5_parent_ids is None

    def test_parent_hit_without_chunk_hit(self):
        from scripts.evaluation.runner import _apply_id_metrics

        result, question = self._pair(chunk_ids=("c9",), parent_ids=("p1",))
        _apply_id_metrics(
            result,
            question,
            {"relevant_chunk_ids": ["c2"], "relevant_parent_ids": ["p1"]},
            8,
        )
        assert result.recall_at_5_ids == 0.0
        assert result.recall_at_5_parent_ids == 1.0


class TestApplyLegacyMetrics:
    def _pair(self, *, answerable=True):
        from types import SimpleNamespace

        result = SimpleNamespace(
            retrieved_contexts=["[1] 合同期限3个月以上不满1年：试用期1个月"],
            recall_at_5=None,
            recall_at_final_k=None,
            mrr=None,
            ndcg_at_5=None,
            ndcg_at_final_k=None,
        )
        question = SimpleNamespace(
            answerable=answerable,
            relevant_contexts=["合同期限3个月以上不满1年：试用期1个月"],
        )
        return result, question

    def test_answerable_question_gets_scores(self):
        from scripts.evaluation.runner import _apply_legacy_metrics

        result, question = self._pair()
        _apply_legacy_metrics(result, question, 8)
        assert result.recall_at_5 == 1.0
        assert result.mrr == 1.0

    def test_unanswerable_question_gets_none_not_zero(self):
        from scripts.evaluation.runner import _apply_legacy_metrics

        result, question = self._pair(answerable=False)
        _apply_legacy_metrics(result, question, 8)
        assert result.recall_at_5 is None
        assert result.recall_at_final_k is None
        assert result.mrr is None
        assert result.ndcg_at_5 is None

    def test_empty_gold_stays_none(self):
        from scripts.evaluation.runner import _apply_legacy_metrics

        result, question = self._pair()
        question.relevant_contexts = []
        _apply_legacy_metrics(result, question, 8)
        assert result.recall_at_5 is None
