"""LLM 版 gold 对齐：解决"人工写的 gold 片段在语料里找不到原文"的问题。

实测：85 题 189 条 gold 片段，用确定性匹配（归一化子串 / bigram≥0.92）只有 122 条
能落到 chunk 上，20 道题完全落不到——因为 gold 是人工复述，不是原文摘录。
本模块用"词法粗筛 top-N 候选 + LLM 抽取式二选"补足，并保留可校验性：
LLM 只能从候选里选、返回的 ID 必须存在、与词法结果的交集作为一致率上报。
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from scripts.evaluation.gold_grounding import _bigrams, normalize_for_match

logger = structlog.get_logger(__name__)

_CANDIDATE_SYSTEM_PROMPT = (
    "你是严格的检索标注员。给定一个问题和若干候选文档片段（带 chunk_id），"
    "只挑选『回答问题所必需的证据』所在的片段。规则：\n"
    "1) 只能使用候选列表里出现的 chunk_id，禁止编造；\n"
    "2) 只选真正包含答案依据的片段，包含同主题但没有答案的片段不要选；\n"
    "3) 若候选里没有任何片段能支撑回答，返回空数组 [];\n"
    '4) 输出必须是 JSON：{"chunk_ids": ["<id>", ...]}，不要输出其他内容。'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def prefilter_candidates(
    question: str,
    relevant_contexts: list[str] | tuple[str, ...] | None,
    chunks: list[dict[str, Any]],
    *,
    top_k: int = 25,
) -> list[dict[str, Any]]:
    """词法粗筛：按"gold 片段 bigram 覆盖率 + 问题词重合"给 chunk 打分取 top_k。

    纯计算，不调用 LLM；保证每道题都把最可能的片段喂给 LLM（上下文可控、成本可控）。
    """
    if not chunks:
        return []
    question_bigrams = _bigrams(normalize_for_match(question))
    snippet_bigrams = [
        _bigrams(normalize_for_match(s))
        for s in (relevant_contexts or [])
        if normalize_for_match(s)
    ]

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, chunk in enumerate(chunks):
        text_bigrams = _bigrams(normalize_for_match(chunk.get("chunk_text")))
        if not text_bigrams:
            continue
        best = 0.0
        for sb in snippet_bigrams:
            if not sb:
                continue
            best = max(best, len(sb & text_bigrams) / len(sb))
        q_score = 0.0
        if question_bigrams:
            q_score = len(question_bigrams & text_bigrams) / len(question_bigrams)
        score = best * 2.0 + q_score
        if score > 0:
            scored.append((score, index, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [chunk for _, _, chunk in scored[: max(1, top_k)]]


def build_grounding_messages(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    max_chars_per_candidate: int = 700,
) -> list[dict[str, str]]:
    """构造候选片段 prompt（编号 + chunk_id + 章节路径 + 截断正文）。"""
    blocks: list[str] = []
    for candidate in candidates:
        text = str(candidate.get("chunk_text") or "").strip().replace("\n", " ")
        if len(text) > max_chars_per_candidate:
            text = text[:max_chars_per_candidate] + "…"
        section = str(candidate.get("section_path") or "").strip()
        blocks.append(
            f'<candidate chunk_id="{candidate.get("chunk_id")}"'
            + (f' section="{section}"' if section else "")
            + f">{text}</candidate>"
        )
    user = (
        f"问题：{question}\n\n"
        f"候选片段（共 {len(candidates)} 条）：\n" + "\n".join(blocks) + "\n\n"
        "请返回覆盖回答所需证据的 chunk_id 列表（JSON）。"
    )
    return [
        {"role": "system", "content": _CANDIDATE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_grounding_response(text: str | None, valid_ids: set[str]) -> list[str]:
    """解析 LLM 返回的 chunk_id 列表；只保留候选里真实存在的 ID（防编造）。"""
    if not text:
        return []
    raw = str(text).strip()
    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    payload: Any = None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None

    if payload is None:
        # 退化路径：JSON 解析失败时抓文本里的数字 ID（仍受 valid_ids 约束）
        candidates: list[Any] = re.findall(r"\d+", raw)
    elif isinstance(payload, dict):
        candidates = payload.get("chunk_ids") or payload.get("ids") or []
    elif isinstance(payload, list):
        candidates = payload
    else:
        candidates = []

    ids: list[str] = []
    for item in candidates:
        if isinstance(item, dict):
            item = item.get("chunk_id") or item.get("id")
        key = str(item).strip()
        if key and key in valid_ids and key not in ids:
            ids.append(key)
    return ids


async def ground_dataset_with_llm(
    questions: list[Any],
    chunks: list[dict[str, Any]],
    *,
    model: str | None = None,
    concurrency: int = 4,
    top_k: int = 25,
    min_ratio: float = 0.92,
) -> dict[str, dict[str, Any]]:
    """LLM 抽取式对齐：每题粗筛候选 → LLM 只从候选选 ID → 与词法结果比对。

    返回 ``{question_id: {"relevant_chunk_ids": [...], "relevant_parent_ids": [...],
    "ungrounded": [...], "lexical_chunk_ids": [...], "candidates": int}}``。
    LLM 调用失败时该题退化为词法结果（fail-open，不中断整批）。
    """
    import asyncio

    from app.common.llm_client import get_chat_client
    from app.infra.model_fallback import ModelFallbackManager
    from scripts.evaluation.gold_grounding import ground_question

    parent_of = {
        str(chunk.get("chunk_id")): str(chunk.get("parent_block_id") or "") for chunk in chunks
    }
    fallback = ModelFallbackManager(client=get_chat_client())
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, dict[str, Any]] = {}

    async def _one(question: Any) -> None:
        qid = str(getattr(question, "id", "") or "")
        text = str(getattr(question, "question", "") or "")
        snippets = list(getattr(question, "relevant_contexts", None) or [])
        candidates = prefilter_candidates(text, snippets, chunks, top_k=top_k)
        valid_ids = {str(c.get("chunk_id")) for c in candidates}
        lexical = ground_question(snippets, chunks, min_ratio=min_ratio)
        lexical_ids = [str(i) for i in lexical["relevant_chunk_ids"]]

        llm_ids: list[str] = []
        if candidates and text:
            async with semaphore:
                try:
                    resp = await fallback.chat_completion(
                        model=model,
                        messages=build_grounding_messages(text, candidates),
                        temperature=0.0,
                        max_tokens=300,
                    )
                    content = resp.choices[0].message.content
                    llm_ids = parse_grounding_response(content, valid_ids)
                except Exception as e:  # noqa: BLE001 - 单题失败不拖垮整批
                    logger.warning("llm gold grounding failed", question_id=qid, error=str(e))

        chosen = llm_ids or lexical_ids
        parent_ids: list[str] = []
        for cid in chosen:
            pid = parent_of.get(cid) or ""
            if pid and pid not in parent_ids:
                parent_ids.append(pid)
        results[qid] = {
            "relevant_chunk_ids": chosen,
            "relevant_parent_ids": parent_ids,
            "ungrounded": [] if chosen else snippets,
            "lexical_chunk_ids": lexical_ids,
            "candidates": len(candidates),
            "source": "llm" if llm_ids else ("lexical" if lexical_ids else "none"),
        }

    await asyncio.gather(*[_one(q) for q in questions])

    grounded = [v for v in results.values() if v["relevant_chunk_ids"]]
    llm_sourced = [v for v in results.values() if v["source"] == "llm"]
    agree = [v for v in llm_sourced if set(v["relevant_chunk_ids"]) & set(v["lexical_chunk_ids"])]
    logger.info(
        "llm gold grounding done",
        questions=len(results),
        grounded=len(grounded),
        llm_sourced=len(llm_sourced),
        lexical_agree=len(agree),
    )
    return results
