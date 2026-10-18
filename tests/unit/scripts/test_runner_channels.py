"""Task 0 量尺：gold_mode、通道隔离、子集过滤。"""

from scripts.evaluation.datasets.base import EvalQuestion, EvalResult


def test_gold_mode_defaults_to_all():
    q = EvalQuestion(id="t1", question="q", ground_truth_answer="a")
    assert q.gold_mode == "all"


def test_any_of_question_scores_hit_when_any_gold_retrieved():
    from scripts.evaluation.runner import _apply_id_metrics

    q = EvalQuestion(
        id="t2",
        question="q",
        ground_truth_answer="a",
        relevant_chunk_ids=["c1", "c2", "c3"],
        gold_mode="any_of",
    )
    r = EvalResult(question_id="t2", question="q", retrieved_chunk_ids=["c3"])
    _apply_id_metrics(r, q, {}, 8)
    assert r.recall_at_5_ids == 1.0
    assert r.mrr_ids == 1.0


class TestChannelSelection:
    def test_channel_selection_vector_only_disables_keyword(self, monkeypatch):
        from app.config import get_settings
        from scripts.evaluation.runner import _apply_channel_selection

        settings = get_settings()
        monkeypatch.setattr(settings.rag, "keyword_channel_enabled", True, raising=False)
        _apply_channel_selection("vector", settings)
        assert settings.rag.keyword_channel_enabled is False

    def test_channel_selection_keyword_only_disables_vector(self, monkeypatch):
        from app.config import get_settings
        from scripts.evaluation.runner import _apply_channel_selection

        settings = get_settings()
        monkeypatch.setattr(settings.rag, "vector_channel_enabled", True, raising=False)
        _apply_channel_selection("keyword", settings)
        assert settings.rag.vector_channel_enabled is False

    def test_channel_selection_both_keeps_defaults(self):
        from app.config import get_settings
        from scripts.evaluation.runner import _apply_channel_selection

        settings = get_settings()
        before = (settings.rag.vector_channel_enabled, settings.rag.keyword_channel_enabled)
        _apply_channel_selection("both", settings)
        after = (settings.rag.vector_channel_enabled, settings.rag.keyword_channel_enabled)
        assert after == before


class TestSubsetFilter:
    def test_subset_filters_by_id_prefix(self):
        from scripts.evaluation.runner import _filter_subset

        qs = [
            EvalQuestion(id="emp001", question="q1", ground_truth_answer="a"),
            EvalQuestion(id="lex001", question="q2", ground_truth_answer="a"),
        ]
        assert [q.id for q in _filter_subset(qs, "emp")] == ["emp001"]
        assert [q.id for q in _filter_subset(qs, "lex")] == ["lex001"]
        assert len(_filter_subset(qs, "all")) == 2


def test_subset_unans_keeps_every_unanswerable_question():
    from scripts.evaluation.datasets.base import EvalQuestion
    from scripts.evaluation.runner import _filter_subset

    qs = [
        EvalQuestion(id="emp001", question="问题一是什么？", ground_truth_answer="a"),
        EvalQuestion(id="ref001", question="问题二是什么？", ground_truth_answer="b", answerable=False, expected_refusal=True),
        EvalQuestion(id="lex001", question="问题三是什么？", ground_truth_answer="c"),
    ]
    got = _filter_subset(qs, "unans")
    assert [q.id for q in got] == ["ref001"]
