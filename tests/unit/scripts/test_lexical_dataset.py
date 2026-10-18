"""编号类题库契约：30 题（15 dev / 15 test）、gold 必填、子类型齐全。"""

from scripts.evaluation.datasets.combined import ALL_QUESTIONS
from scripts.evaluation.datasets.lexical_dataset import LEXICAL_DATASET


def test_lexical_dataset_has_30_questions_split_evenly():
    assert len(LEXICAL_DATASET) == 30
    splits = [q.metadata.get("split_hint") for q in LEXICAL_DATASET]
    assert splits.count("dev") == 15
    assert splits.count("test") == 15


def test_every_lexical_question_has_gold_chunk_ids():
    for q in LEXICAL_DATASET:
        assert q.relevant_chunk_ids, f"{q.id} 缺 gold chunk_id"
        assert q.relevant_contexts, f"{q.id} 缺 relevant_contexts（旧口径仍要用）"


def test_clause_questions_are_marked_and_subtyped():
    for q in LEXICAL_DATASET:
        assert q.metadata.get("question_kind") == "lexical"
        assert q.metadata.get("lexical_subtype") in {
            "clause_doc",
            "clause_sub",
            "clause_grade",
            "clause_ambiguous",
        }


def test_ambiguous_questions_use_any_of_gold_mode():
    for q in LEXICAL_DATASET:
        if q.metadata.get("lexical_subtype") == "clause_ambiguous":
            assert q.gold_mode == "any_of"
            assert len(q.relevant_chunk_ids) >= 2


def test_combined_dataset_keeps_employee_questions_first():
    assert len(ALL_QUESTIONS) == 115
    assert ALL_QUESTIONS[0].id == "emp001"
    assert ALL_QUESTIONS[-1].id.startswith("lex")
