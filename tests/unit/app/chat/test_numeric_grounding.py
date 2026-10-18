"""数字落地校验：回答里的量必须能在它引用的证据里找到；这是 judge 判不准的那 20/85 道数值题。

规则刻意保守：只查"带单位的量"，不查条款号、编号列表、引用编号；
宁可漏报（交给 LLM 复核），也不要把"800 元/晚"这种正确引用误判成编造。
"""

from __future__ import annotations

from app.chat.numeric_grounding import (
    extract_quantities,
    numeric_issues,
    polarity_issues,
)


def _ref(ref_id, content, child=""):
    return {"reference_id": ref_id, "content": content, "child_chunk_text": child}


class TestExtractQuantities:
    def test_extracts_quantity_with_unit(self):
        found = extract_quantities("每日住宿上限 800 元/晚，补贴 100 元。")
        assert (800.0, "元") in [(v, u) for v, u, _ in found]
        assert (100.0, "元") in [(v, u) for v, u, _ in found]

    def test_ignores_clause_numbers(self):
        assert [v for v, _, _ in extract_quantities("按第9条与第 12 条执行")] == []

    def test_ignores_bare_integers_without_unit(self):
        # 无单位的裸数字（列表序号、版本号）不参与数字落地，避免误判
        assert extract_quantities("第 1 点如下") == []

    def test_ignores_citation_markers(self):
        assert extract_quantities("补贴 100 元 [1]") == [(100.0, "元", "100 元")]

    def test_percent(self):
        assert (70.0, "%") in [(v, u) for v, u, _ in extract_quantities("报销比例 70%")]


class TestNumericIssues:
    def test_correct_citation_has_no_issue(self):
        answer = "总监级 M4+ 在 A 类城市每日住宿上限 800 元 [1]。"
        references = [
            _ref(1, "**9.1** 总监级及以上（M4+）在 A 类城市出差，每日住宿上限为 800 元/晚，含税。")
        ]
        assert numeric_issues(answer, references) == []

    def test_tampered_number_is_flagged(self):
        answer = "总监级在 A 类城市每日住宿上限 807 元 [1]。"
        references = [_ref(1, "每日住宿上限为 800 元/晚，含税。")]
        issues = numeric_issues(answer, references)
        assert len(issues) == 1
        assert "807" in issues[0].raw
        assert issues[0].ref_ids == [1]

    def test_number_found_in_any_cited_evidence_passes(self):
        answer = "补贴 100 元 [1][2]。"
        references = [_ref(1, "住宿上限 800 元。"), _ref(2, "餐饮补贴 100 元。")]
        assert numeric_issues(answer, references) == []

    def test_wan_yuan_is_converted(self):
        answer = "年度上限 50000 元 [1]。"
        references = [_ref(1, "年度培训预算上限为 5 万元。")]
        assert numeric_issues(answer, references) == []

    def test_sentence_without_citation_is_skipped(self):
        # 没有引用编号的句子归 audit_grounding 的 uncited_claims 管，这里不重复报
        assert numeric_issues("每日住宿上限 807 元。", [_ref(1, "800 元")]) == []

    def test_child_chunk_text_takes_priority(self):
        answer = "餐补 100 元 [1]。"
        references = [
            _ref(1, "父块还有很多别的内容 800 元", child="第10条 餐饮补贴：每日 100 元。")
        ]
        assert numeric_issues(answer, references) == []

    def test_missing_reference_is_reported(self):
        issues = numeric_issues("上限 800 元 [3]。", [_ref(1, "800 元")])
        assert issues and issues[0].ref_ids == [3]

    def test_empty_answer_is_clean(self):
        assert numeric_issues("", []) == []


class TestPolarityIssues:
    """证据禁止、回答放行 —— 判据模型看不见的极性翻转。"""

    def test_permission_against_prohibition_is_flagged(self):
        issues = polarity_issues(
            "员工可以申请将客户数据带离办公场所[1]。",
            [{"reference_id": 1, "content": "员工禁止将客户数据带离办公场所。"}],
        )
        assert len(issues) == 1
        assert issues[0].ref_ids == [1]

    def test_verbatim_prohibition_is_not_flagged(self):
        issues = polarity_issues(
            "员工禁止将客户数据带离办公场所[1]。",
            [{"reference_id": 1, "content": "员工禁止将客户数据带离办公场所。"}],
        )
        assert issues == []

    def test_permission_without_prohibition_evidence_is_fine(self):
        issues = polarity_issues(
            "员工可以申请年假[1]。",
            [{"reference_id": 1, "content": "员工可以申请年假，需提前三天提交。"}],
        )
        assert issues == []

    def test_negation_in_answer_keeps_it_safe(self):
        issues = polarity_issues(
            "员工不可以将客户数据带离办公场所[1]。",
            [{"reference_id": 1, "content": "员工禁止将客户数据带离办公场所。"}],
        )
        assert issues == []

    def test_uncited_permission_is_not_our_business(self):
        issues = polarity_issues(
            "员工可以带离。",
            [{"reference_id": 1, "content": "员工禁止将客户数据带离办公场所。"}],
        )
        assert issues == []

    def test_missing_reference_text_is_skipped(self):
        issues = polarity_issues(
            "员工可以带离[3]。",
            [{"reference_id": 1, "content": "员工禁止将客户数据带离办公场所。"}],
        )
        assert issues == []
