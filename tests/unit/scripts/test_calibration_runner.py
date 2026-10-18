"""标定执行器：把样本喂给判据、收集概率、按类型汇总。判据通过参数注入，便于离线单测。"""

from __future__ import annotations

import pytest

from scripts.evaluation.calibration_cases import CalibrationCase
from scripts.evaluation.calibration_runner import case_to_state, evaluate_cases


def _case(kind: str, supported: bool, cid: str) -> CalibrationCase:
    return CalibrationCase(
        case_id=cid,
        kind=kind,
        criterion="citation_support",
        expected_supported=supported,
        question="出差住宿上限是多少？",
        answer="每日住宿上限 807 元/晚 [1]" if not supported else "每日住宿上限 800 元/晚 [1]",
        evidence="总监级及以上（M4+）A 类城市每日住宿上限 800 元/晚",
        chunk_id="c1",
        document_name="差旅制度.md",
        gold_chunk_id="c1",
        gold_document_name="差旅制度.md",
    )


class TestCaseToState:
    def test_state_carries_question_answer_and_evidence(self):
        state = case_to_state(_case("verbatim", True, "a"))
        assert "出差住宿上限是多少？" in state
        assert "800 元/晚" in state
        assert "[1]" in state


class TestEvaluateCases:
    async def test_groups_rows_by_kind_and_computes_auc(self):
        cases = [
            _case("verbatim", True, "v1"),
            _case("verbatim", True, "v2"),
            _case("doc_swap", False, "d1"),
            _case("doc_swap", False, "d2"),
        ]

        async def judge(case):
            return 0.9 if case.expected_supported else 0.1

        report = await evaluate_cases(cases, judge)
        assert report["overall"]["n"] == 4
        assert report["overall"]["auc"] == pytest.approx(1.0)
        assert report["by_kind"]["verbatim"]["positives"] == 2
        assert report["by_kind"]["doc_swap"]["negatives"] == 2
        assert len(report["rows"]) == 4

    async def test_judge_failure_is_excluded_instead_of_scored_zero(self):
        cases = [_case("verbatim", True, "v1"), _case("doc_swap", False, "d1")]

        async def judge(case):
            if case.kind == "doc_swap":
                raise RuntimeError("service down")
            return 0.8

        report = await evaluate_cases(cases, judge)
        assert report["overall"]["n"] == 1
        assert report["errors"] == ["d1"]

    async def test_missing_probability_is_treated_as_error(self):
        cases = [_case("verbatim", True, "v1")]

        async def judge(case):
            return None

        report = await evaluate_cases(cases, judge)
        assert report["overall"]["n"] == 0
        assert report["errors"] == ["v1"]
