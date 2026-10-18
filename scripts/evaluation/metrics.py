from __future__ import annotations

import math
import random
import re
from typing import Any

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
    """评估生成答案与标准答案的事实一致性（统一代理至 AnswerCorrectnessMetric）。

    返回 0.0 ~ 1.0 分数。
    """
    if not generated_answer or not ground_truth_answer:
        return 0.0

    from app.observability.metrics.answer_correctness import AnswerCorrectnessMetric

    metric = AnswerCorrectnessMetric()
    try:
        res = await metric.ascore(
            question=question,
            answer=generated_answer,
            contexts=[],
            ground_truth=ground_truth_answer,
        )
        return float(res.value)
    except Exception as e:
        logger.warning(
            "compute_answer_correctness failed, fallback to direct scoring", error=str(e)
        )
        # 兜底：直接使用原有 LLM prompt 打分
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
        rel_str = str(relevant).strip()
        if not rel_str:
            continue
        rel_bigrams = _char_bigrams(rel_str)
        if not rel_bigrams:
            # 极短词（如单字/英文缩写），降级为直接子串匹配
            matched = any(rel_str.lower() in ret.lower() for ret in top_k)
        else:
            matched = any(
                len(rel_bigrams & _char_bigrams(ret)) / len(rel_bigrams) >= 0.5 for ret in top_k
            )
        if matched:
            recalled += 1
    return recalled / len(relevant_contexts)


def _covered(relevant: str, text: str) -> bool:
    """单条检索结果是否覆盖某标注片段（与 compute_recall_at_k 同口径：bigram 重合 ≥ 0.5）。"""
    rel = str(relevant).strip()
    if not rel:
        return False
    rb = _char_bigrams(rel)
    if not rb:
        return rel.lower() in (text or "").lower()
    return len(rb & _char_bigrams(text or "")) / len(rb) >= 0.5


def compute_mrr(
    retrieved_contexts: list[str],
    relevant_contexts: list[str],
) -> float:
    """MRR：首个覆盖到任一标注片段的检索结果的排名倒数（1-based）。"""
    if not relevant_contexts or not retrieved_contexts:
        return 0.0
    for rank, ret in enumerate(retrieved_contexts, start=1):
        if any(_covered(rel, ret) for rel in relevant_contexts):
            return round(1.0 / rank, 4)
    return 0.0


def compute_ndcg_at_k(
    retrieved_contexts: list[str],
    relevant_contexts: list[str],
    k: int,
) -> float:
    """nDCG@k（二值相关性，每条标注片段最多计一次），评估排序质量。"""
    if not relevant_contexts or not retrieved_contexts or k <= 0:
        return 0.0
    used: set[int] = set()
    gains: list[float] = []
    for ret in retrieved_contexts[:k]:
        hit = -1
        for i, rel in enumerate(relevant_contexts):
            if i in used:
                continue
            if _covered(rel, ret):
                hit = i
                break
        if hit >= 0:
            used.add(hit)
            gains.append(1.0)
        else:
            gains.append(0.0)
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal_n = min(k, len(relevant_contexts))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_n))
    return round(dcg / idcg, 4) if idcg > 0 else 0.0


def compute_lexical_context_recall(
    retrieved_contexts: list[str],
    relevant_contexts: list[str],
) -> float:
    """计算词法级上下文召回率（用于快速离线字符重合实验分析）。"""
    if not relevant_contexts or not retrieved_contexts:
        return 0.0

    retrieved_bigram_sets = [_char_bigrams(c) for c in retrieved_contexts]

    matched = 0
    for ctx in relevant_contexts:
        ctx_str = str(ctx).strip()
        if not ctx_str:
            matched += 1
            continue
        ctx_bigrams = _char_bigrams(ctx_str)
        if not ctx_bigrams:
            found = any(ctx_str.lower() in ret.lower() for ret in retrieved_contexts)
            if found:
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


async def compute_semantic_context_recall(
    question: str,
    retrieved_contexts: list[str],
    ground_truth_answer: str,
) -> float:
    """学术标准 RAGAS NLI 语义命题覆盖 Context Recall（代理至 ContextRecallMetric）。"""
    if not ground_truth_answer or not retrieved_contexts:
        return 0.0
    from app.observability.metrics.context_recall import ContextRecallMetric

    metric = ContextRecallMetric()
    try:
        res = await metric.ascore(
            question=question,
            answer="",
            contexts=retrieved_contexts,
            ground_truth=ground_truth_answer,
        )
        return float(res.value)
    except Exception as e:
        logger.warning("compute_semantic_context_recall failed", error=str(e))
        return 0.0


# 保持向后兼容别名
compute_context_recall = compute_lexical_context_recall


def _parse_score(text: str) -> float:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```.*?\n", "", text)
        text = re.sub(r"\n```$", "", text)
    text = text.strip()
    score_match = re.search(
        r"(?:score|得分|分数|rating)[^\d]*(\b100|\b[1-9]?[0-9])\b",
        text,
        re.IGNORECASE,
    )
    if score_match:
        return float(score_match.group(1))
    nums = re.findall(r"\b(100|[1-9]?[0-9])\b", text)
    if nums:
        return float(nums[-1])
    return 0.0


# ── 配对 bootstrap：判定两次评测差值是否显著 ──────────────────────────────


def paired_bootstrap_delta(
    base: list[float],
    opt: list[float],
    *,
    n_boot: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """对同一批问题上的指标差值做配对 bootstrap，返回 delta / CI / 双侧 p。

    逐题配对后重采样题目索引（同一索引两边同时取），保留问题难度分布，
    比直接比较两个均值更不容易把噪声当成收益。
    """
    if len(base) != len(opt):
        raise ValueError(f"paired series length mismatch: {len(base)} vs {len(opt)}")

    n = len(base)
    if n == 0:
        return {
            "n": 0,
            "delta": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "p_value": 1.0,
            "significant": False,
        }

    diffs = [float(o) - float(b) for b, o in zip(base, opt, strict=True)]
    delta = sum(diffs) / n

    rng = random.Random(seed)
    boot: list[float] = []
    for _ in range(n_boot):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        boot.append(total / n)
    boot.sort()

    lo = boot[int(alpha / 2 * n_boot)]
    hi = boot[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    le = sum(1 for x in boot if x <= 0) / n_boot
    ge = sum(1 for x in boot if x >= 0) / n_boot
    p_value = min(1.0, 2 * min(le, ge))

    return {
        "n": n,
        "delta": delta,
        "ci_low": lo,
        "ci_high": hi,
        "p_value": p_value,
        "significant": bool(lo > 0 or hi < 0),
    }


def extract_metric_series(
    base_report: dict[str, Any], opt_report: dict[str, Any], metric: str
) -> tuple[list[float], list[float]]:
    """按 question_id 对齐两份报告的逐题指标，取交集（顺序以 base 为准）。"""
    base_by_id = {
        r.get("question_id"): r.get(metric)
        for r in base_report.get("results", [])
        if r.get(metric) is not None
    }
    opt_by_id = {
        r.get("question_id"): r.get(metric)
        for r in opt_report.get("results", [])
        if r.get(metric) is not None
    }
    base_vals: list[float] = []
    opt_vals: list[float] = []
    for qid, b in base_by_id.items():
        if qid in opt_by_id:
            base_vals.append(float(b))
            opt_vals.append(float(opt_by_id[qid]))
    return base_vals, opt_vals


# ─────────────────────────────────────────────────────────────────────
# Task 1：按证据 ID 判定的召回指标
#
# 旧口径（compute_recall_at_k）拿 gold 片段和"提升后的父块全文（≤4000 字符）"
# 做字符 bigram 重合判定，8 条上下文 ≈3 万字符，几乎必然命中 → R@K 虚高。
# 检索结果本身带 chunk_id / parent_block_id，直接按 ID 精确判定排名质量。
# gold 为空（拒答题）返回 None，由调用方剔除，不再记 0 分拉低均值。
# ─────────────────────────────────────────────────────────────────────


def _id_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _id_set(values: Any) -> set[str]:
    if not values:
        return set()
    return {key for raw in values if (key := _id_key(raw))}


def compute_id_recall_at_k(
    retrieved_ids: list[Any],
    gold_ids: set[Any] | list[Any] | tuple[Any, ...],
    k: int,
) -> float | None:
    """Recall@K：前 K 条证据的 ID 覆盖了多少条 gold ID。

    返回 None 表示该题没有 gold（拒答题/空标注），不应计入均值。
    """
    gold = _id_set(gold_ids)
    if not gold:
        return None
    if k <= 0:
        return 0.0
    top = {key for raw in (retrieved_ids or [])[:k] if (key := _id_key(raw))}
    if not top:
        return 0.0
    return round(len(gold & top) / len(gold), 4)


def compute_id_mrr(
    retrieved_ids: list[Any],
    gold_ids: set[Any] | list[Any] | tuple[Any, ...],
) -> float | None:
    """MRR：首个命中 gold ID 的名次倒数（1-based）。"""
    gold = _id_set(gold_ids)
    if not gold:
        return None
    for rank, raw in enumerate(retrieved_ids or [], start=1):
        if _id_key(raw) in gold:
            return round(1.0 / rank, 4)
    return 0.0


def compute_id_ndcg_at_k(
    retrieved_ids: list[Any],
    gold_ids: set[Any] | list[Any] | tuple[Any, ...],
    k: int,
) -> float | None:
    """nDCG@k（二值相关性，每条 gold 只计一次增益）。"""
    gold = _id_set(gold_ids)
    if not gold:
        return None
    if k <= 0:
        return 0.0
    seen: set[str] = set()
    gains: list[float] = []
    for raw in (retrieved_ids or [])[:k]:
        key = _id_key(raw)
        if key and key in gold and key not in seen:
            seen.add(key)
            gains.append(1.0)
        else:
            gains.append(0.0)
    dcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains))
    ideal_n = min(k, len(gold))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_n))
    return round(dcg / idcg, 4) if idcg > 0 else 0.0
