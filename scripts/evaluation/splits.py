"""dev/test 切分（Task 4）：按**文档**切，而不是按题目随机切。

按题随机切会让同一份文档的相邻条款同时出现在 dev 与 test 里，检索器只要记住
句子就能"泛化"，评测会系统性高估。按文档切之后，test 里的文档在调参阶段从未出现。
"""

from __future__ import annotations

from typing import Any

TEST_MODULUS = 4


def is_test_document(document_id: Any, *, modulus: int = TEST_MODULUS) -> bool:
    """文档级切分：id % modulus == 0 进 test（约 1/modulus）。"""
    if document_id is None:
        return False
    try:
        value = int(str(document_id).strip())
    except (TypeError, ValueError):
        # 非数字文档 ID：用稳定哈希决定，保证可复现
        return sum(ord(ch) for ch in str(document_id)) % modulus == 0
    return value % modulus == 0


def question_split(
    question: Any, chunk_docs: dict[str, Any], *, modulus: int = TEST_MODULUS
) -> str:
    """判断一道题属于 dev 还是 test：看它的 gold chunk 落在哪些文档。

    - 题目自带 `metadata["split_hint"]`（人工分好的题库）→ 以它为准
    - 没有 gold（不可答/无标注）→ dev（只在 dev 上做对比，避免污染 test）
    - 任一 gold chunk 属于 test 文档 → test
    """
    hint = (getattr(question, "metadata", None) or {}).get("split_hint")
    if hint in {"dev", "test"}:
        return hint
    gold_ids = list(getattr(question, "relevant_chunk_ids", None) or [])
    for cid in gold_ids:
        doc = chunk_docs.get(str(cid))
        if doc is not None and is_test_document(doc, modulus=modulus):
            return "test"
    return "dev"


def filter_by_split(
    questions: list[Any],
    chunk_docs: dict[str, Any],
    split: str,
    *,
    modulus: int = TEST_MODULUS,
) -> list[Any]:
    """split="all" 时原样返回。"""
    if split == "all":
        return list(questions)
    return [q for q in questions if question_split(q, chunk_docs, modulus=modulus) == split]
