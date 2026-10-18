"""判据标定指标：AUC（区分度）、ECE（置信度是否可信）、阈值选择。

设计要点：
- 纯函数、无 IO、无模型调用，便于手算复核与单测；
- "可用"门槛写在 ``summarize`` 里（AUC >= 0.85 且 ECE <= 0.10），
  避免有人拿一个 AUC 0.6 的判据去改生产阈值；
- ``choose_threshold`` 只在满足误放预算（false pass）的前提下最大化放行率，
  因为"放行"意味着跳过昂贵的 LLM 复核，误放比误拦代价高。
"""

from __future__ import annotations

from collections.abc import Iterable

AUC_FLOOR = 0.85
ECE_CEILING = 0.10


def auc(positives: Iterable[float], negatives: Iterable[float]) -> float | None:
    """Mann-Whitney AUC（并列按 0.5 计）。任一集合为空返回 None。"""
    pos = [float(p) for p in positives if p is not None]
    neg = [float(n) for n in negatives if n is not None]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def expected_calibration_error(
    probabilities: Iterable[float], labels: Iterable[int], *, bins: int = 10
) -> float | None:
    """按等宽分箱计算 ECE（各箱 |平均置信度 - 实际正确率| 的样本加权和）。"""
    probs = [float(p) for p in probabilities]
    truth = [1 if int(v) else 0 for v in labels]
    if not probs or len(probs) != len(truth):
        return None
    buckets: dict[int, list[tuple[float, int]]] = {}
    for prob, label in zip(probs, truth, strict=True):
        index = min(int(prob * bins), bins - 1)
        if index < 0:
            index = 0
        buckets.setdefault(index, []).append((prob, label))
    total = len(probs)
    error = 0.0
    for items in buckets.values():
        mean_prob = sum(p for p, _ in items) / len(items)
        mean_label = sum(v for _, v in items) / len(items)
        error += abs(mean_prob - mean_label) * len(items) / total
    return error


def choose_threshold(
    rows: Iterable[tuple[float, int]],
    *,
    max_false_pass: float = 0.05,
) -> dict[str, float] | None:
    """在误放率不超过 ``max_false_pass`` 的前提下，选放行率最高的阈值。

    ``rows`` 是 (置信度, 是否真的被支持) 序列；返回
    ``{"threshold", "true_pass_rate", "false_pass_rate", "precision"}``。
    找不到满足预算的阈值时返回 None（意味着该判据不能单独决策）。
    """
    data = [(float(p), 1 if int(v) else 0) for p, v in rows]
    if not data:
        return None
    positives = [p for p, v in data if v == 1]
    negatives = [p for p, v in data if v == 0]
    if not positives or not negatives:
        return None

    best: dict[str, float] | None = None
    for threshold in sorted({p for p, _ in data}):
        tp = sum(1 for p in positives if p >= threshold)
        fp = sum(1 for p in negatives if p >= threshold)
        false_pass = fp / len(negatives)
        if false_pass > max_false_pass + 1e-12:
            continue
        candidate = {
            "threshold": threshold,
            "true_pass_rate": tp / len(positives),
            "false_pass_rate": false_pass,
            "precision": tp / (tp + fp) if (tp + fp) else 0.0,
        }
        if best is None or candidate["true_pass_rate"] > best["true_pass_rate"]:
            best = candidate
    return best


def summarize(rows: Iterable[tuple[float, int]], *, threshold: float = 0.5) -> dict:
    """汇总一个判据的标定结果；``usable`` 是"能不能拿它去改生产阈值"的结论。"""
    data = [(float(p), 1 if int(v) else 0) for p, v in rows]
    probs = [p for p, _ in data]
    labels = [v for _, v in data]
    positives = [p for p, v in data if v == 1]
    negatives = [p for p, v in data if v == 0]

    tpr = (sum(1 for p in positives if p >= threshold) / len(positives)) if positives else None
    fpr = (sum(1 for p in negatives if p >= threshold) / len(negatives)) if negatives else None
    balanced = ((tpr or 0.0) + (1 - (fpr or 0.0))) / 2 if positives and negatives else None
    discrimination = auc(positives, negatives)
    calibration = expected_calibration_error(probs, labels)
    return {
        "n": len(data),
        "positives": len(positives),
        "negatives": len(negatives),
        "base_rate": (len(positives) / len(data)) if data else None,
        "auc": discrimination,
        "ece": calibration,
        "threshold": threshold,
        "true_pass_rate": tpr,
        "false_pass_rate": fpr,
        "pass_rate_at_threshold": (
            sum(1 for p in probs if p >= threshold) / len(probs) if probs else None
        ),
        "balanced_accuracy_at_0.5": balanced,
        "usable": bool(
            discrimination is not None
            and calibration is not None
            and discrimination >= AUC_FLOOR
            and calibration <= ECE_CEILING
        ),
    }
