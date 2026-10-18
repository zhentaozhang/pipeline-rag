"""拒答/不可答判定测试（Task 2）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.evaluation.refusal import (
    build_refusal_messages,
    classify_refusal,
    parse_refusal_response,
    refusal_rates,
)


class TestClassifyRefusal:
    @pytest.mark.parametrize(
        "answer",
        [
            "员工手册中未规定宠物相关事项，建议咨询人力资源部。",
            "抱歉，现有制度中没有相关内容，无法回答。",
            "公司规定不允许携带宠物进入办公区，因此该问题无法回答。",
            "该事项不属于本手册适用范围，建议咨询相关部门。",
        ],
    )
    def test_refusal_answers_are_detected(self, answer):
        assert classify_refusal(answer) is True

    @pytest.mark.parametrize(
        "answer",
        [
            "试用期为1至6个月，视合同期限而定。",
            "根据第12条规定，报销时限为30个工作日。",
            "年假天数为5天、10天或15天，按工龄计算。",
        ],
    )
    def test_concrete_answers_are_not_refusals(self, answer):
        assert classify_refusal(answer) is False

    def test_empty_answer_is_undecidable(self):
        assert classify_refusal("") is None
        assert classify_refusal(None) is None

    def test_vague_answer_without_markers_is_undecidable(self):
        # 既没有拒答措辞，也没有具体数值/条款 → 交给 LLM 判，兜底不栽赃
        assert classify_refusal("请参考公司相关规定执行。") is None


class TestParseRefusalResponse:
    def test_parses_true_and_false(self):
        assert parse_refusal_response('{"refused": true}') is True
        assert parse_refusal_response('{"refused": false}') is False

    def test_tolerates_code_fence_and_prose(self):
        assert parse_refusal_response('结论如下：\n```json\n{"refused": true}\n```') is True

    @pytest.mark.parametrize("text", ["", None, "不知道", '{"other": 1}', "{broken"])
    def test_undecidable_payloads(self, text):
        assert parse_refusal_response(text) is None


class TestBuildRefusalMessages:
    def test_contains_question_and_answer(self):
        messages = build_refusal_messages("能带宠物吗？", "公司不允许携带宠物。")
        assert messages[0]["role"] == "system"
        assert "refused" in messages[0]["content"]
        assert "能带宠物吗？" in messages[1]["content"]
        assert "公司不允许携带宠物。" in messages[1]["content"]


class TestRefusalRates:
    def _r(self, refused, *, expected=True, status="completed"):
        return SimpleNamespace(expected_refusal=expected, refused=refused, status=status)

    def test_counts_only_expected_refusal_cases(self):
        results = [
            self._r(True),
            self._r(False),
            self._r(None),
            self._r(True, expected=False),
            self._r(True, status="failed"),
        ]
        rates = refusal_rates(results)
        assert rates["refusal_cases"] == 3
        assert rates["correct_refusal_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert rates["false_answer_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_no_refusal_cases_returns_none(self):
        rates = refusal_rates([self._r(True, expected=False)])
        assert rates["correct_refusal_rate"] is None
        assert rates["false_answer_rate"] is None
        assert rates["refusal_cases"] == 0
