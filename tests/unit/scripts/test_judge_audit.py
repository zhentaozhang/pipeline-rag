"""`scripts/evaluation/judge_audit.py` 的纯函数测试（judge 灵敏度/稳定性审计）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.evaluation.judge_audit import (
    aggregate,
    auc,
    build_audit_cases,
    swap_numbers,
)


class TestAuc:
    def test_perfect_separation(self) -> None:
        assert auc([0.9, 0.8], [0.2, 0.1]) == 1.0

    def test_identical_scores_is_half(self) -> None:
        assert auc([0.5, 0.5], [0.5]) == 0.5

    def test_inverted_is_zero(self) -> None:
        assert auc([0.1], [0.9]) == 0.0

    def test_partial_tie_counts_half(self) -> None:
        # 0.5 对 0.5 记 0.5，0.5 对 0.1 记 1.0 → (1.0+0.5)/2
        assert auc([0.5], [0.5, 0.1]) == 0.75

    def test_empty_side_returns_none(self) -> None:
        assert auc([], [0.5]) is None
        assert auc([0.5], []) is None


class TestSwapNumbers:
    def test_numbers_are_changed(self) -> None:
        out = swap_numbers("满 1 年报销 100% 考试费，上限 3000 元", seed=1)
        assert out != "满 1 年报销 100% 考试费，上限 3000 元"
        assert "考试费" in out and "元" in out

    def test_decimal_structure_kept(self) -> None:
        out = swap_numbers("第 5.1 条规定", seed=3)
        assert out.startswith("第 ")
        assert "." in out

    def test_text_without_numbers_unchanged(self) -> None:
        assert swap_numbers("没有任何数字") == "没有任何数字"

    def test_deterministic_for_same_seed(self) -> None:
        assert swap_numbers("123 456", seed=7) == swap_numbers("123 456", seed=7)

    def test_empty_string(self) -> None:
        assert swap_numbers("") == ""


def _q(qid: str, answerable: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=qid,
        question=f"{qid} 的问题？",
        ground_truth_answer=f"{qid} 的答案",
        answerable=answerable,
    )


def _chunks() -> tuple[dict[str, str], dict[str, str]]:
    texts = {
        "1": "条款一：" + "员工年假每年 5 天，可跨年顺延，报销上限 3000 元。" * 6,
        "2": "条款二：" + "出差住宿标准为每晚六百元。" * 8,
        "3": "条款三：" + "数据安全等级分为四级。" * 8,
    }
    docs = {"1": "doc:1", "2": "doc:2", "3": "doc:3"}
    return texts, docs


class TestBuildAuditCases:
    def test_produces_three_kinds(self) -> None:
        texts, docs = _chunks()
        cases = build_audit_cases([_q("a")], {"a": ["1"]}, texts, docs, limit=1, seed=0)
        kinds = {c["kind"] for c in cases}
        assert kinds == {"good", "wrong_doc", "number_swap"}

    def test_wrong_doc_comes_from_another_document(self) -> None:
        texts, docs = _chunks()
        cases = build_audit_cases([_q("a")], {"a": ["1"]}, texts, docs, limit=1, seed=0)
        wrong = next(c for c in cases if c["kind"] == "wrong_doc")
        assert "条款一" not in wrong["answer"]

    def test_skips_question_without_gold(self) -> None:
        texts, docs = _chunks()
        assert build_audit_cases([_q("a")], {}, texts, docs, limit=5) == []

    def test_skips_unanswerable_question(self) -> None:
        texts, docs = _chunks()
        cases = build_audit_cases([_q("a", answerable=False)], {"a": ["1"]}, texts, docs, limit=5)
        assert cases == []

    def test_respects_limit(self) -> None:
        texts, docs = _chunks()
        cases = build_audit_cases(
            [_q("a"), _q("b"), _q("c")],
            {"a": ["1"], "b": ["2"], "c": ["3"]},
            texts,
            docs,
            limit=2,
        )
        assert len({c["question_id"] for c in cases}) == 2

    def test_good_answer_uses_gold_text(self) -> None:
        texts, docs = _chunks()
        cases = build_audit_cases([_q("a")], {"a": ["1"]}, texts, docs, limit=1)
        good = next(c for c in cases if c["kind"] == "good")
        assert "员工年假每年 5 天" in good["answer"]


class TestAggregate:
    def test_auc_and_gap(self) -> None:
        runs = [
            {"question_id": "a", "kind": "good", "repeat": 0, "faithfulness": 0.9},
            {"question_id": "a", "kind": "wrong_doc", "repeat": 0, "faithfulness": 0.2},
        ]
        stats = aggregate(runs, ["faithfulness"])["faithfulness"]
        assert stats["n_good"] == 1 and stats["n_bad"] == 1
        assert stats["auc"] == 1.0
        assert stats["mean_good_minus_bad"] == pytest.approx(0.7)

    def test_retest_drift(self) -> None:
        runs = [
            {"question_id": "a", "kind": "good", "repeat": 0, "faithfulness": 0.9},
            {"question_id": "a", "kind": "good", "repeat": 1, "faithfulness": 0.7},
        ]
        stats = aggregate(runs, ["faithfulness"])["faithfulness"]
        assert stats["retest_mean_abs_drift"] == pytest.approx(0.2)
        assert stats["retest_max_drift"] == pytest.approx(0.2)

    def test_missing_metric_rows_ignored(self) -> None:
        runs = [{"question_id": "a", "kind": "good", "repeat": 0}]
        stats = aggregate(runs, ["faithfulness"])["faithfulness"]
        assert stats["n_good"] == 0
        assert stats["auc"] is None
