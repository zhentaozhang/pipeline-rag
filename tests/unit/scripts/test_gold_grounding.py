"""gold 片段 → chunk_id 对齐（Task 1）。

背景：现有 85 题的 gold 是自由文本片段，检索结果带 chunk_id，两者无法直接比对。
本模块把片段**确定性地**对齐到已入库 chunk（子串包含优先，退化时用字符 bigram 覆盖率），
从而把召回判定从"bigram 撞上父块 4000 字"改成"命中目标 chunk id"。
"""

from __future__ import annotations

from scripts.evaluation.gold_grounding import (
    ground_gold_chunks,
    ground_question,
    normalize_for_match,
)

CHUNKS = [
    {
        "chunk_id": 1,
        "parent_block_id": 10,
        "chunk_text": "第5条 试用期规定 劳动合同期限三个月以上不满一年的，试用期不得超过一个月。",
    },
    {
        "chunk_id": 2,
        "parent_block_id": 10,
        "chunk_text": "第6条 劳动合同期限一年以上不满三年的，试用期不得超过二个月。",
    },
    {
        "chunk_id": 3,
        "parent_block_id": 11,
        "chunk_text": "第9条 年休假 员工累计工作满1年不满10年的，年休假5天。",
    },
]


class TestNormalizeForMatch:
    def test_strips_whitespace_and_punctuation(self):
        assert normalize_for_match("试用期 不得超过，二个月。") == "试用期不得超过二个月"

    def test_lowercases_ascii(self):
        assert normalize_for_match("SLA 99.9%") == "sla999"

    def test_empty_input(self):
        assert normalize_for_match("") == ""
        assert normalize_for_match(None) == ""


class TestGroundQuestion:
    def test_exact_substring_grounds_chunk_and_parent(self):
        out = ground_question(["试用期不得超过二个月"], CHUNKS)
        assert out["relevant_chunk_ids"] == ["2"]
        assert out["relevant_parent_ids"] == ["10"]
        assert out["ungrounded"] == []

    def test_whitespace_and_punctuation_insensitive(self):
        out = ground_question(["试用期 不得超过，二个月"], CHUNKS)
        assert out["relevant_chunk_ids"] == ["2"]

    def test_multiple_chunks_in_same_parent_are_all_grounded(self):
        out = ground_question(["劳动合同期限"], CHUNKS)
        assert set(out["relevant_chunk_ids"]) == {"1", "2"}
        assert out["relevant_parent_ids"] == ["10"]

    def test_ungrounded_snippet_is_reported_not_silently_dropped(self):
        out = ground_question(["完全不存在的制度条款"], CHUNKS)
        assert out["relevant_chunk_ids"] == []
        assert out["relevant_parent_ids"] == []
        assert out["ungrounded"] == ["完全不存在的制度条款"]

    def test_blank_snippets_ignored(self):
        out = ground_question(["", "   ", "年休假5天"], CHUNKS)
        assert out["relevant_chunk_ids"] == ["3"]
        assert out["ungrounded"] == []

    def test_no_snippets_returns_empty(self):
        out = ground_question([], CHUNKS)
        assert out == {"relevant_chunk_ids": [], "relevant_parent_ids": [], "ungrounded": []}

    def test_prefix_preserved_for_chunks_with_longer_text(self):
        """片段是 chunk 的子串（评测集常态），必须稳定命中。"""
        out = ground_question(["员工累计工作满1年不满10年的"], CHUNKS)
        assert out["relevant_chunk_ids"] == ["3"]


class TestGroundGoldChunks:
    def test_returns_per_question_mapping(self):
        questions = [
            {"id": "q1", "relevant_contexts": ["试用期不得超过二个月"]},
            {"id": "q2", "relevant_contexts": ["年休假5天"]},
        ]
        out = ground_gold_chunks(questions, CHUNKS)
        assert out["q1"]["relevant_chunk_ids"] == ["2"]
        assert out["q2"]["relevant_chunk_ids"] == ["3"]

    def test_supports_pydantic_question_objects(self):
        from scripts.evaluation.datasets.base import EvalQuestion

        questions = [
            EvalQuestion(
                id="q1",
                question="试用期多久",
                ground_truth_answer="二个月",
                relevant_contexts=["试用期不得超过二个月"],
            )
        ]
        out = ground_gold_chunks(questions, CHUNKS)
        assert out["q1"]["relevant_chunk_ids"] == ["2"]

    def test_question_without_gold_is_kept_as_empty(self):
        questions = [{"id": "q1", "relevant_contexts": []}]
        out = ground_gold_chunks(questions, CHUNKS)
        assert out["q1"] == {
            "relevant_chunk_ids": [],
            "relevant_parent_ids": [],
            "ungrounded": [],
        }

    def test_min_ratio_is_configurable(self):
        """低相关度片段只有在放宽阈值后才被接受。"""
        near = [
            {
                "chunk_id": 9,
                "parent_block_id": 90,
                "chunk_text": "员工累计工作满1年不满10年的，年休假5天。",
            }
        ]
        snippet = ["员工累计工作满1年不满10年，年休假为5天"]
        strict = ground_question(snippet, near, min_ratio=0.99)
        lenient = ground_question(snippet, near, min_ratio=0.5)
        assert strict["relevant_chunk_ids"] == []
        assert lenient["relevant_chunk_ids"] == ["9"]
