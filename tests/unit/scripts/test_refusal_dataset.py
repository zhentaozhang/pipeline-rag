"""拒答题库扩容：n=7 时跨跑差 1 题就跳 0.14，等于不可判。"""

from __future__ import annotations

from scripts.evaluation.datasets import ALL_QUESTIONS
from scripts.evaluation.datasets.refusal_dataset import REFUSAL_DATASET
from scripts.evaluation.splits import question_split


def test_refusal_set_is_large_enough_to_judge():
    assert len(REFUSAL_DATASET) >= 20


def test_every_refusal_question_is_unanswerable_with_a_reason():
    for q in REFUSAL_DATASET:
        assert q.answerable is False, q.id
        assert q.expected_refusal is True, q.id
        assert q.relevant_contexts == [] and q.relevant_chunk_ids == [], q.id
        assert q.metadata.get("unanswerable_reason"), q.id


def test_ids_are_unique_and_do_not_collide_with_the_main_set():
    ids = [q.id for q in REFUSAL_DATASET]
    assert len(ids) == len(set(ids))
    others = {q.id for q in ALL_QUESTIONS if q.id not in set(ids)}
    assert not (set(ids) & others)


def test_split_is_balanced_so_the_test_set_can_judge_refusal():
    hints = [q.metadata.get("split_hint") for q in REFUSAL_DATASET]
    assert hints.count("dev") >= 8 and hints.count("test") >= 8


def test_both_unanswerable_families_are_present():
    reasons = {q.metadata["unanswerable_reason"] for q in REFUSAL_DATASET}
    assert {"no_policy_in_corpus", "nonexistent_clause"} <= reasons


def test_questions_are_questions():
    for q in REFUSAL_DATASET:
        assert q.question.endswith(("？", "?")), q.id
        assert len(q.question) >= 8, q.id


def test_split_hint_is_honoured_by_question_split():
    chunk_docs = {}
    for q in REFUSAL_DATASET:
        assert question_split(q, chunk_docs) == q.metadata["split_hint"]
