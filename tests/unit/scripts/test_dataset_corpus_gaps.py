"""两份缺失制度灌入语料后，"语料缺口题"必须变成可答题。

历史背景：emp010/016/021/033/040 的问题是"语料里没有这两份文档"，
所以此前被标成 answerable=False（召回指标跳过、只看拒答率）。
把 03 信息安全与数据保密管理规范、06 员工在职进修与专业资格考证补贴办法
灌进索引之后，它们就该回到正常可答题——否则题库会持续骗人。
"""

from __future__ import annotations

from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET
from scripts.evaluation.datasets.refusal_dataset import REFUSAL_DATASET

_GAP_IDS = {"emp010", "emp016", "emp021", "emp033", "emp040"}


def test_corpus_gap_questions_are_answerable_now():
    by_id = {q.id: q for q in EMPLOYEE_DATASET}
    for qid in _GAP_IDS:
        q = by_id[qid]
        assert q.answerable is True, qid
        assert q.expected_refusal is False, qid
        assert q.relevant_chunk_ids, f"{qid} 缺少 gold chunk"
        assert "unanswerable_reason" not in q.metadata, qid


def test_no_question_still_claims_a_missing_source_document():
    reasons = {(q.metadata or {}).get("unanswerable_reason") for q in EMPLOYEE_DATASET}
    assert "source_document_absent" not in reasons


def test_refusal_set_does_not_ask_about_a_document_we_now_index():
    """ref016 曾问"进修补贴办法"的认证考试费；该文档入索引后它不再成立。"""
    for q in REFUSAL_DATASET:
        assert "认证考试" not in q.question, q.id
