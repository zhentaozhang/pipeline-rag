from __future__ import annotations

import re

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


async def compute_answer_correctness(
    fallback,
    question: str,
    generated_answer: str,
    ground_truth_answer: str,
) -> float:
    """评估生成答案与标准答案的事实一致性。

    LLM-as-judge，返回 0.0 ~ 1.0 分数。
    """
    if not generated_answer or not ground_truth_answer:
        return 0.0

    system = "你是一个评估助手。比较 生成答案 和 标准答案 的事实一致性。"
    user = (
        f"问题：{question}\n\n"
        f"生成答案：{generated_answer}\n\n"
        f"标准答案：{ground_truth_answer}\n\n"
        "判分规则（严格遵循）：\n"
        "1. 生成答案包含标准答案的全部关键事实（允许措辞不同）= 100 分；\n"
        "2. 生成答案在完整覆盖关键事实基础上补充了额外信息 = 仍 100 分（补充不扣分）；\n"
        "3. 只覆盖部分关键事实 = 按覆盖比例给分（如 2/3 关键事实 = 67 分）；\n"
        "4. 关键事实与标准答案矛盾 = 该项 0 分。\n"
        "返回一个 0-100 的整数分数（0=完全不一致，100=完全一致）。只返回数字。"
    )

    resp = await fallback.chat_completion(
        model=None,
        temperature=0.0,
        max_tokens=256,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    score_text = resp.choices[0].message.content or "0"
    return max(0.0, min(1.0, _parse_score(score_text) / 100.0))


_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]+")
_ALPHANUM_RE = re.compile(r"[a-zA-Z0-9_]+")


def _char_bigrams(text: str) -> set[str]:
    """将文本拆分为字符级 2-gram（同时兼容中文和英文）"""
    text = re.sub(r"\s+", "", text.lower())
    text = re.sub(r"[^\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaffa-zA-Z0-9_]", "", text)
    return {text[i : i + 2] for i in range(len(text) - 1)}


def compute_recall_at_k(
    retrieved_contexts: list[str],
    relevant_contexts: list[str],
    k: int,
) -> float:
    """Recall@K：检索结果前 K 条中覆盖的应检上下文比例（量化能力 #2）"""
    if not relevant_contexts:
        return 0.0
    top_k = retrieved_contexts[:k]
    if not top_k:
        return 0.0
    recalled = 0
    for relevant in relevant_contexts:
        rel_bigrams = _char_bigrams(relevant)
        if not rel_bigrams:
            continue
        matched = any(
            len(rel_bigrams & _char_bigrams(ret)) / len(rel_bigrams) >= 0.5
            for ret in top_k
        )
        if matched:
            recalled += 1
    return recalled / len(relevant_contexts)


def compute_context_recall(
    retrieved_contexts: list[str],
    relevant_contexts: list[str],
) -> float:
    """计算上下文召回率：应检出的上下文中，有多少被实际检索到。

    使用字符 bigrams 跨语言对比，无须分词（兼容中文/英文混合文本）。
    """
    if not relevant_contexts:
        return 0.0

    if not retrieved_contexts:
        return 0.0

    retrieved_bigram_sets = [_char_bigrams(c) for c in retrieved_contexts]

    matched = 0
    for ctx in relevant_contexts:
        ctx_bigrams = _char_bigrams(ctx)
        if not ctx_bigrams:
            matched += 1
            continue

        found = False
        for ret_bigrams in retrieved_bigram_sets:
            overlap = len(ctx_bigrams & ret_bigrams)
            if overlap / len(ctx_bigrams) >= 0.35:
                found = True
                break

        if found:
            matched += 1

    return matched / len(relevant_contexts)


def _parse_score(text: str) -> float:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```.*?\n", "", text)
        text = re.sub(r"\n```$", "", text)
    text = text.strip()
    nums = re.findall(r"\d+", text)
    if nums:
        return float(nums[0])
    return 0.0
