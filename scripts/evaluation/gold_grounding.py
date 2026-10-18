"""标注片段 → chunk_id 对齐（Task 1：召回口径改造的地基）。

为什么需要：现有离线评测集的 gold 是**自由文本片段**（人写的），而检索结果带的是
`chunk_id`。旧指标只能拿片段文本去和"提升后的父块全文（最长 4000 字符）"做字符
bigram 重合判定，命中门槛低到几乎必然命中，导致 R@K 系统性虚高。本模块把片段
**确定性地**对齐到已入库 chunk，使召回可以按 ID 精确判定。

匹配口径（按优先级）：
1. 归一化（去空白/标点、转小写）后，片段是 chunk 文本的子串 —— 评测集常态，最可靠；
2. 否则字符 bigram 覆盖率 ≥ ``min_ratio``（默认 0.92，允许少量措辞/标点差异）。

命中不了的片段不会被静默丢弃，而是进 ``ungrounded`` 列表，供人工/LLM 复核——
这是"标注质量可被度量"的一部分。
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 空白 + 中英文标点（归一化只服务匹配，不改变任何回写文本）
_PUNCT_RE = re.compile(
    r"[\s\u3000，。、；：？！“”‘’（）《》〈〉【】〖〗…—－·%‰℃,.;:?!\"'()\[\]{}<>\-—_/\\|~`@#$^&*+=]+"
)


def normalize_for_match(text: Any) -> str:
    """归一化文本用于匹配：去空白与标点、ASCII 转小写。"""
    if not text:
        return ""
    return _PUNCT_RE.sub("", str(text)).lower()


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _field(chunk: Any, *names: str) -> Any:
    if isinstance(chunk, dict):
        for name in names:
            if chunk.get(name) is not None:
                return chunk.get(name)
        return None
    for name in names:
        value = getattr(chunk, name, None)
        if value is not None:
            return value
    return None


def _as_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _prepare_chunks(chunks: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    """预归一化 chunk 文本；已预处理过的列表原样返回（避免重复 O(n) 计算）。"""
    if chunks and isinstance(chunks[0], dict) and "norm" in chunks[0]:
        return list(chunks)
    prepared: list[dict[str, Any]] = []
    for chunk in chunks or []:
        text = _field(chunk, "chunk_text", "text") or ""
        norm = normalize_for_match(text)
        prepared.append(
            {
                "chunk_id": _as_id(_field(chunk, "chunk_id", "id")),
                "parent_block_id": _as_id(_field(chunk, "parent_block_id")),
                "norm": norm,
                "bigrams": _bigrams(norm),
            }
        )
    return prepared


def _snippet_matches(norm_snippet: str, chunk: dict[str, Any], min_ratio: float) -> bool:
    if not norm_snippet:
        return False
    if norm_snippet in chunk["norm"]:
        return True
    snippet_bigrams = _bigrams(norm_snippet)
    if not snippet_bigrams:
        return False
    chunk_bigrams: set[str] = chunk["bigrams"]
    if not chunk_bigrams:
        return False
    return len(snippet_bigrams & chunk_bigrams) / len(snippet_bigrams) >= min_ratio


def ground_question(
    snippets: list[str] | tuple[str, ...] | None,
    chunks: list[Any] | tuple[Any, ...],
    *,
    min_ratio: float = 0.92,
) -> dict[str, list[str]]:
    """把一条题目的 gold 片段对齐成 chunk_id / parent_block_id 列表。"""
    prepared = _prepare_chunks(list(chunks))
    chunk_ids: list[str] = []
    parent_ids: list[str] = []
    ungrounded: list[str] = []

    for raw in snippets or []:
        norm = normalize_for_match(raw)
        if not norm:
            continue
        matched = [c for c in prepared if _snippet_matches(norm, c, min_ratio)]
        if not matched:
            ungrounded.append(str(raw).strip())
            continue
        for chunk in matched:
            if chunk["chunk_id"] and chunk["chunk_id"] not in chunk_ids:
                chunk_ids.append(chunk["chunk_id"])
            if chunk["parent_block_id"] and chunk["parent_block_id"] not in parent_ids:
                parent_ids.append(chunk["parent_block_id"])

    return {
        "relevant_chunk_ids": chunk_ids,
        "relevant_parent_ids": parent_ids,
        "ungrounded": ungrounded,
    }


def ground_gold_chunks(
    questions: list[Any] | tuple[Any, ...],
    chunks: list[Any] | tuple[Any, ...],
    *,
    min_ratio: float = 0.92,
) -> dict[str, dict[str, list[str]]]:
    """批量对齐：``{question_id: {"relevant_chunk_ids": [...], ...}}``。"""
    prepared = _prepare_chunks(list(chunks))
    grounded: dict[str, dict[str, list[str]]] = {}
    for question in questions or []:
        qid = _as_id(_field(question, "id"))
        snippets = _field(question, "relevant_contexts") or []
        grounded[qid] = ground_question(snippets, prepared, min_ratio=min_ratio)
    if grounded:
        total = sum(len(v["relevant_chunk_ids"]) for v in grounded.values())
        ungrounded = sum(len(v["ungrounded"]) for v in grounded.values())
        logger.info(
            "gold chunks grounded",
            questions=len(grounded),
            chunk_hits=total,
            ungrounded_snippets=ungrounded,
        )
    return grounded
