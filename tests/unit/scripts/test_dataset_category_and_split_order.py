"""数据集分类标签 + 切分顺序（先 gold 对齐，再切分）的回归测试。

两个都是"文档写了但代码没做"的缺陷：
1. `--sample-per-category` 靠 id 区间硬编码，而分类只写在 docstring 里；
   现在给每题写 `metadata["category"]`，采样优先读标签。
2. `filter_by_split` 在 gold 对齐之前跑，而它读 `question.relevant_chunk_ids`——
   手写题这一列是空的，于是按文档切分退化成"全部落 dev"，test 集形同虚设。
"""

from __future__ import annotations

from scripts.evaluation.datasets import load_dataset
from scripts.evaluation.runner import _attach_grounded_gold, _category_counts


def test_every_employee_question_carries_a_category() -> None:
    questions = [q for q in load_dataset() if q.id.startswith("emp")]
    assert len(questions) == 85
    missing = [q.id for q in questions if not q.metadata.get("category")]
    assert missing == []


def test_category_counts_cover_the_five_buckets() -> None:
    questions = [q for q in load_dataset() if q.id.startswith("emp")]
    counts = _category_counts(questions)
    assert counts == {
        "numeric_limit": 20,
        "conditional_branch": 18,
        "cross_document": 17,
        "time_version": 15,
        "safety_boundary": 15,
    }


def test_attach_grounded_gold_fills_missing_ids_only() -> None:
    questions = [
        load_dataset()[0].model_copy(update={"relevant_chunk_ids": []}),
        load_dataset()[1].model_copy(update={"relevant_chunk_ids": ["keep-me"]}),
    ]
    grounded = {
        questions[0].id: {"relevant_chunk_ids": ["c1"], "relevant_parent_ids": ["p1"]},
        questions[1].id: {"relevant_chunk_ids": ["ignored"], "relevant_parent_ids": ["p2"]},
    }
    filled = _attach_grounded_gold(questions, grounded)
    assert filled == 1
    assert questions[0].relevant_chunk_ids == ["c1"]
    assert questions[0].relevant_parent_ids == ["p1"]
    # 题目自带 gold 的，不被对齐结果覆盖
    assert questions[1].relevant_chunk_ids == ["keep-me"]

