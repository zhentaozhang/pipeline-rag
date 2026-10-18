"""judge 可信度审计（Task 3）：灵敏度 / 特异性 / 重测稳定性。

没有人工标注的情况下，无法直接算 judge 与人的一致性。可行的替代是**构造已知优劣的答案对**：
同一道题给三份答案——
1. `good`：直接摘录该题 gold chunk（应当高分）
2. `wrong_doc`：摘录一份**别的文档**的条款（内容像制度、但与本题无关，应当低分）
3. `number_swap`：把 good 答案里的数字改掉（措辞几乎一样、事实错了，应当低分）

看 judge 能否把 good 与 bad 分开（AUC），以及同一份输入重复判分的抖动（重测稳定性）。
这两个数是"相信后续所有 faithfulness / correctness 提升"的前提。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def auc(good_scores: list[float], bad_scores: list[float]) -> float | None:
    """good 相对 bad 的 ROC AUC（并列记 0.5）。

    AUC=1.0 表示 judge 把每个好答案都排在所有坏答案之上；0.5 表示与抛硬币无异。
    """
    good = [float(x) for x in good_scores if x is not None]
    bad = [float(x) for x in bad_scores if x is not None]
    if not good or not bad:
        return None
    wins = 0.0
    for g in good:
        for b in bad:
            if g > b:
                wins += 1.0
            elif g == b:
                wins += 0.5
    return wins / (len(good) * len(bad))


def swap_numbers(text: str, *, seed: int = 0) -> str:
    """把文本里的数字改成"形似而错"的值（保留位数结构），用于构造事实错误的答案。

    没有数字可改时原样返回，调用方应跳过该样本。
    """
    rng = random.Random(seed)

    def _mutate(match: re.Match[str]) -> str:
        raw = match.group(0)
        sep = "," if "," in raw else ("." if "." in raw else "")
        digits = raw.replace(",", "").replace(".", "")
        if not digits:
            return raw
        new_digits = "".join(str((int(ch) + rng.choice([1, 2, -1])) % 10) for ch in digits)
        if new_digits == digits:  # 极端情况下没变，强制改首位
            new_digits = str((int(digits[0]) + 3) % 10) + digits[1:]
        if sep and len(new_digits) > 1:
            return new_digits[:-1] + sep + new_digits[-1] if sep == "." else raw
        return new_digits

    return _NUM_RE.sub(_mutate, text)


def build_audit_cases(
    questions: list[Any],
    gold_chunks: dict[str, list[str]],
    chunk_texts: dict[str, str],
    chunk_docs: dict[str, str],
    *,
    limit: int = 12,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """构造 (good / wrong_doc / number_swap) 三类对照答案。"""
    pool = [q for q in questions if getattr(q, "answerable", True)]
    rng = random.Random(seed)
    rng.shuffle(pool)

    cases: list[dict[str, Any]] = []
    used = 0  # limit 是"题数"，不是 case 数
    for q in pool:
        if used >= limit:
            break
        gold_ids = list(gold_chunks.get(q.id) or [])
        if not gold_ids:
            continue
        good_text = "\n".join(chunk_texts.get(str(cid), "") for cid in gold_ids).strip()
        if len(good_text) < 80:
            continue
        own_docs = {chunk_docs.get(str(cid), "") for cid in gold_ids}

        foreign = [
            cid
            for cid, doc in chunk_docs.items()
            if doc and doc not in own_docs and len(chunk_texts.get(str(cid), "")) >= 80
        ]
        if not foreign:
            continue
        foreign_id = rng.choice(sorted(foreign))

        cases.append(
            {
                "question_id": q.id,
                "question": q.question,
                "ground_truth": q.ground_truth_answer,
                "contexts": [good_text],
                "kind": "good",
                "answer": good_text[:1500],
            }
        )
        cases.append(
            {
                "question_id": q.id,
                "question": q.question,
                "ground_truth": q.ground_truth_answer,
                "contexts": [good_text],
                "kind": "wrong_doc",
                "answer": chunk_texts.get(str(foreign_id), "")[:1500],
            }
        )
        used += 1
        swapped = swap_numbers(good_text, seed=seed)
        if swapped != good_text:
            cases.append(
                {
                    "question_id": q.id,
                    "question": q.question,
                    "ground_truth": q.ground_truth_answer,
                    "contexts": [good_text],
                    "kind": "number_swap",
                    "answer": swapped[:1500],
                }
            )
    return cases


async def _score_case(judge: Any, case: dict[str, Any], metrics: list[str]) -> dict[str, float]:
    results = await judge.run(
        question=case["question"],
        answer=case["answer"],
        contexts=list(case["contexts"]),
        ground_truth=case["ground_truth"],
    )
    return {
        r.metric_name: float(r.value) for r in results if r.metric_name in metrics and not r.failed
    }


def _build_pipeline() -> Any:
    """只装 faithfulness + answer_correctness 两条指标，把审计成本压到一半。"""
    from app.common.llm_client import get_eval_client
    from app.config import get_settings
    from app.observability.metrics.answer_correctness import AnswerCorrectnessMetric
    from app.observability.metrics.faithfulness import FaithfulnessMetric
    from app.observability.metrics.pipeline import EvaluationPipeline

    settings = get_settings()
    model = settings.rag.evaluation_model or settings.llm.model
    eval_llm = get_eval_client()
    return EvaluationPipeline(
        [
            FaithfulnessMetric(eval_llm=eval_llm, model=model),
            AnswerCorrectnessMetric(eval_llm=eval_llm, model=model),
        ]
    )


async def audit(cases: list[dict[str, Any]], *, repeats: int, concurrency: int) -> dict[str, Any]:
    pipeline = _build_pipeline()
    metrics = ["faithfulness", "answer_correctness"]

    semaphore = asyncio.Semaphore(concurrency)

    async def _one(case: dict[str, Any], rep: int) -> dict[str, Any]:
        async with semaphore:
            scores = await _score_case(pipeline, case, metrics)
        return {**{k: v for k, v in case.items() if k != "contexts"}, "repeat": rep, **scores}

    runs = await asyncio.gather(*[_one(c, r) for c in cases for r in range(repeats)])
    return {"metrics": aggregate(list(runs), metrics), "runs": list(runs)}


def aggregate(runs: list[dict[str, Any]], metrics: list[str]) -> dict[str, Any]:
    """把重复判分结果聚合成每指标的灵敏度（AUC）与重测抖动。"""
    per_metric: dict[str, Any] = {}
    for metric in metrics:
        by_kind: dict[str, list[float]] = {}
        by_case: dict[tuple[str, str], list[float]] = {}
        for row in runs:
            if metric not in row:
                continue
            by_kind.setdefault(row["kind"], []).append(row[metric])
            by_case.setdefault((row["question_id"], row["kind"]), []).append(row[metric])

        good = by_kind.get("good", [])
        bad = [*by_kind.get("wrong_doc", []), *by_kind.get("number_swap", [])]
        drifts = [max(vals) - min(vals) for vals in by_case.values() if len(vals) > 1]
        mean_good = sum(good) / len(good) if good else None
        mean_bad = sum(bad) / len(bad) if bad else None
        separation = auc(good, bad)
        per_metric[metric] = {
            "n_good": len(good),
            "n_bad": len(bad),
            "mean_good": None if mean_good is None else round(mean_good, 4),
            "mean_bad": None if mean_bad is None else round(mean_bad, 4),
            "auc": None if separation is None else round(separation, 4),
            "mean_good_minus_bad": (
                None if mean_good is None or mean_bad is None else round(mean_good - mean_bad, 4)
            ),
            "retest_mean_abs_drift": round(sum(drifts) / len(drifts), 4) if drifts else None,
            "retest_max_drift": round(max(drifts), 4) if drifts else None,
            "by_kind": {
                kind: {"n": len(vals), "mean": round(sum(vals) / len(vals), 4)}
                for kind, vals in by_kind.items()
            },
        }
    return per_metric


async def _load_chunks() -> tuple[dict[str, str], dict[str, str]]:
    from sqlalchemy import select

    from app.db.models.document import DocumentChunk
    from app.db.session import get_session_factory, init_db

    await init_db()
    factory = get_session_factory()
    assert factory is not None
    chunk_texts: dict[str, str] = {}
    chunk_docs: dict[str, str] = {}
    async with factory() as session:
        rows = (
            await session.execute(
                select(DocumentChunk.id, DocumentChunk.chunk_text, DocumentChunk.document_id)
            )
        ).all()
    for row in rows:
        chunk_texts[str(row[0])] = row[1] or ""
        chunk_docs[str(row[0])] = f"doc:{row[2]}"
    return chunk_texts, chunk_docs


async def _amain(args: argparse.Namespace) -> dict[str, Any]:
    from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET

    gold = json.loads(Path(args.gold_file).read_text(encoding="utf-8"))["questions"]
    chunk_texts, chunk_docs = await _load_chunks()

    gold_chunks = {qid: v.get("relevant_chunk_ids") or [] for qid, v in gold.items()}
    cases = build_audit_cases(
        EMPLOYEE_DATASET, gold_chunks, chunk_texts, chunk_docs, limit=args.limit
    )
    try:
        result = await audit(cases, repeats=args.repeats, concurrency=args.concurrency)
    finally:
        from app.db.session import close_db

        await close_db()
    Path(args.out).write_text(
        json.dumps({**result, "cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="judge 灵敏度/稳定性审计")
    parser.add_argument("--gold-file", default="reports/gold_llm.json")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default="reports/judge_audit.json")
    args = parser.parse_args(argv)

    result = asyncio.run(_amain(args))
    for metric, stats in result["metrics"].items():
        logger.info(
            "judge audit",
            metric=metric,
            auc=stats["auc"],
            mean_good=stats["mean_good"],
            mean_bad=stats["mean_bad"],
            gap=stats["mean_good_minus_bad"],
            retest_drift=stats["retest_mean_abs_drift"],
        )
    logger.info("judge audit written", path=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
