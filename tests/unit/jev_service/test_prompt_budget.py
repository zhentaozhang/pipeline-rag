"""JEV Prompt 预算：截断必须发生在 state 上，绝不能砍掉判断标准/证据。"""

from __future__ import annotations

import pytest

from jev_service.prompt_budget import (
    TRUNCATION_MARKER,
    fit_state_to_budget,
    truncate_text_by_tokens,
)


def _count(text: str) -> int:
    """假分词器：中文语境下约 0.5 token/字符（与实测 Qwen2.5 接近）。"""
    return (len(text) + 1) // 2


def _noul_prompt(state: str) -> str:
    return (
        "<|im_start|>system\n判断器<|im_end|>\n"
        "<|im_start|>user\n"
        "判断标准：该论断是否被证据直接支持？证据[3]：" + "证" * 1200 + "\n\n"
        f"待评估内容：\n{state}\n\n"
        "结论（只输出'是'或'否'）：<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


class TestTruncateTextByTokens:
    def test_short_text_is_untouched(self):
        assert truncate_text_by_tokens("短文本", count=_count, budget_tokens=100) == "短文本"

    def test_empty_text(self):
        assert truncate_text_by_tokens("", count=_count, budget_tokens=100) == ""

    def test_result_respects_budget(self):
        text = "甲" * 4000
        for budget in (400, 1000, 2000):
            out = truncate_text_by_tokens(text, count=_count, budget_tokens=budget)
            assert _count(out) <= budget, f"budget={budget} got={_count(out)}"

    def test_keeps_both_ends(self):
        text = "头" * 500 + "中" * 3000 + "尾" * 500
        out = truncate_text_by_tokens(text, count=_count, budget_tokens=600)
        assert out.startswith("头")
        assert out.endswith("尾")
        assert TRUNCATION_MARKER.strip() in out

    def test_marker_reports_truncation(self):
        out = truncate_text_by_tokens("乙" * 5000, count=_count, budget_tokens=500)
        assert "已截断" in out

    def test_tiny_budget_still_returns_something(self):
        out = truncate_text_by_tokens("丙" * 5000, count=_count, budget_tokens=12)
        assert out
        assert _count(out) <= 12 or len(out) < 40


class TestFitStateToBudget:
    def test_short_state_is_untouched(self):
        state = "问题：住宿标准？回答：见第9条[1]。"
        assert (
            fit_state_to_budget(state, count=_count, build_prompt=_noul_prompt, max_tokens=4096)
            == state
        )

    def test_never_drops_the_instructions(self):
        """这是回归的核心：超长 state 时被截的是 state，判断标准与证据必须完整。"""
        state = "答" * 6000  # ≈3000 token
        fitted = fit_state_to_budget(
            state, count=_count, build_prompt=_noul_prompt, max_tokens=1800
        )
        prompt = _noul_prompt(fitted)
        assert _count(prompt) <= 1800
        assert "证" * 1200 in prompt, "证据被截断了"
        assert fitted != state, "state 未被截断（应当先截 state）"

    def test_prompt_still_ends_with_assistant_marker(self):
        fitted = fit_state_to_budget(
            "答" * 6000, count=_count, build_prompt=_noul_prompt, max_tokens=1800
        )
        assert _noul_prompt(fitted).endswith("<|im_start|>assistant\n")

    def test_state_shrinks_when_instructions_are_large(self):
        """判断标准本身就吃掉大半预算时，state 必须让路。"""
        big_inst = "判" * 3000

        def build(state: str) -> str:
            return f"<|im_start|>user\n判断标准：{big_inst}\n待评估内容：\n{state}\n<|im_start|>assistant\n"

        fitted = fit_state_to_budget("答" * 2000, count=_count, build_prompt=build, max_tokens=2000)
        assert _count(build(fitted)) <= 2000
        assert "判" * 3000 in build(fitted)

    def test_degrades_to_minimum_instead_of_raising(self):
        fitted = fit_state_to_budget(
            "答" * 6000,
            count=_count,
            build_prompt=_noul_prompt,
            max_tokens=1,
        )
        assert isinstance(fitted, str)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
