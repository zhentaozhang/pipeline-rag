"""题目"该不该作答"三分法测试（Task 2）。

复盘 20 道疑似"不可答"题后发现三种语义被混为一谈：

1. 无制度依据型（emp071 公车私用 / emp075 携宠上班）：语料无对应制度，正确答案是"无依据"。
2. 语料缺口型（emp010 数据安全分级 / emp016/021/033/040 进修补贴）：题目有标准答案，
   但对应文档不在语料里（语料只有 13/15 份，缺 03 进修补贴办法与 06 数据安全分级）→
   检索注定失败；正确行为是明说无依据，不能编造金额和文件名。
3. 禁止性作答型（emp076-085 中的 10 题）：语料**有**可检索条款，正确答案是给出
   "禁止/不可以"并引用依据 → 它们是正常可答题，把"严禁"当"拒答"会误判为失败。
"""

from __future__ import annotations

from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET

_NO_POLICY_IDS = {"emp071", "emp075"}
_CORPUS_GAP_IDS = {"emp010", "emp016", "emp021", "emp033", "emp040"}
_PROHIBITION_IDS = {f"emp{i:03d}" for i in range(76, 86)}


class TestUnanswerableMarking:
    def _by_id(self):
        return {q.id: q for q in EMPLOYEE_DATASET}

    def test_no_policy_questions_expect_refusal(self):
        by_id = self._by_id()
        for qid in _NO_POLICY_IDS:
            assert by_id[qid].answerable is False, qid
            assert by_id[qid].expected_refusal is True, qid
            assert by_id[qid].metadata["unanswerable_reason"] == "no_policy_in_corpus", qid

    def test_corpus_gap_questions_expect_refusal(self):
        by_id = self._by_id()
        for qid in _CORPUS_GAP_IDS:
            assert by_id[qid].answerable is False, qid
            assert by_id[qid].expected_refusal is True, qid
            assert by_id[qid].metadata["unanswerable_reason"] == "source_document_absent", qid

    def test_prohibition_questions_are_answerable(self):
        by_id = self._by_id()
        for qid in _PROHIBITION_IDS:
            q = by_id[qid]
            assert q.answerable is True, qid
            assert q.expected_refusal is False, qid
            assert q.relevant_contexts, qid
            assert q.metadata.get("question_kind") == "prohibition_with_evidence", qid

    def test_remaining_questions_untouched(self):
        touched = _NO_POLICY_IDS | _CORPUS_GAP_IDS | _PROHIBITION_IDS
        for q in EMPLOYEE_DATASET:
            if q.id in touched:
                continue
            assert q.answerable is True
            assert q.expected_refusal is False
            assert "unanswerable_reason" not in q.metadata
            assert "question_kind" not in q.metadata

    def test_counts(self):
        assert len(EMPLOYEE_DATASET) == 85
        assert sum(1 for q in EMPLOYEE_DATASET if not q.answerable) == 7
        assert sum(1 for q in EMPLOYEE_DATASET if q.expected_refusal) == 7
        answerable = [q for q in EMPLOYEE_DATASET if q.answerable]
        assert len(answerable) == 78
        # 可答题里有 gold 片段的比例（Task 1 语料缺口统计的另一面）
        assert sum(1 for q in answerable if q.relevant_contexts) == len(answerable)
