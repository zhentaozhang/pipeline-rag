"""`scripts/evaluation/splits.py` 的测试。"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.evaluation.splits import (
    filter_by_split,
    is_test_document,
    question_split,
)


class TestIsTestDocument:
    def test_modulus_hit(self) -> None:
        assert is_test_document(8) is True
        assert is_test_document("12") is True

    def test_modulus_miss(self) -> None:
        assert is_test_document(9) is False

    def test_none_is_dev(self) -> None:
        assert is_test_document(None) is False

    def test_non_numeric_is_deterministic(self) -> None:
        assert is_test_document("doc-a") == is_test_document("doc-a")

    def test_custom_modulus(self) -> None:
        assert is_test_document(3, modulus=3) is True


def _q(qid: str, ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(id=qid, relevant_chunk_ids=ids)


class TestQuestionSplit:
    def test_no_gold_goes_dev(self) -> None:
        assert question_split(_q("a", []), {"1": 8}) == "dev"

    def test_gold_in_test_document(self) -> None:
        assert question_split(_q("a", ["1"]), {"1": 8}) == "test"

    def test_gold_in_dev_document(self) -> None:
        assert question_split(_q("a", ["1"]), {"1": 9}) == "dev"

    def test_any_gold_in_test_makes_it_test(self) -> None:
        assert question_split(_q("a", ["1", "2"]), {"1": 9, "2": 8}) == "test"

    def test_unknown_chunk_stays_dev(self) -> None:
        assert question_split(_q("a", ["99"]), {"1": 8}) == "dev"

    def test_explicit_split_hint_wins(self) -> None:
        """编号类题是人工分好 dev/test 的，不能被文档 id 覆盖。"""
        q = _q("a", ["1"])
        q.metadata = {"split_hint": "test"}
        assert question_split(q, {"1": 9}) == "test"
        q_dev = _q("b", ["2"])
        q_dev.metadata = {"split_hint": "dev"}
        assert question_split(q_dev, {"2": 8}) == "dev"


class TestFilterBySplit:
    def test_all_returns_everything(self) -> None:
        qs = [_q("a", ["1"]), _q("b", ["2"])]
        assert filter_by_split(qs, {"1": 8, "2": 9}, "all") == qs

    def test_test_only(self) -> None:
        qs = [_q("a", ["1"]), _q("b", ["2"])]
        assert [q.id for q in filter_by_split(qs, {"1": 8, "2": 9}, "test")] == ["a"]

    def test_dev_includes_ungrounded(self) -> None:
        qs = [_q("a", []), _q("b", ["2"])]
        assert [q.id for q in filter_by_split(qs, {"2": 9}, "dev")] == ["a", "b"]
