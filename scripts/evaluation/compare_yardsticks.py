"""并排比较新旧召回口径（同一批题、同一次检索结果）。

用途：证明"换尺子"不是数字游戏——旧口径（gold 片段 vs 父块全文 bigram≥0.5）与新口径
（chunk_id 精确命中）在同一批检索结果上会给出**双向分歧**，且分歧集中在难题上。

用法：
    env -u NO_PROXY -u no_proxy .venv/bin/python -m scripts.evaluation.compare_yardsticks \
        --report reports/ids_llm.json --gold-file reports/gold_llm.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _mean(values: list[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return sum(kept) / len(kept) if kept else None


def _fmt(value: float | None) -> str:
    return "  N/A" if value is None else f"{value:.4f}"


def _answerable_ids() -> set[str]:
    from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET

    return {q.id for q in EMPLOYEE_DATASET if q.answerable}


def compare(report_path: str, gold_path: str, *, answerable_only: bool = False) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))["questions"]
    grounded = {qid for qid, v in gold.items() if v.get("relevant_chunk_ids")}
    rows = {r["question_id"]: r for r in report["results"]}
    subset = [qid for qid in rows if qid in grounded]
    if answerable_only:
        answerable = _answerable_ids()
        subset = [qid for qid in subset if qid in answerable]

    print(f"报告：{report_path}")
    print(f"gold：{gold_path}")
    print(f"有 chunk 级 gold 的题数：{len(subset)} / {len(rows)}（其余为单位冲突或语料缺失）\n")

    print(f"{'指标':<10}{'旧口径(bigram→父块)':<22}{'新口径(chunk_id)':<20}{'Δ':<10}")
    for name, old_key, new_key in (
        ("R@5", "recall_at_5", "recall_at_5_ids"),
        ("R@8", "recall_at_final_k", "recall_at_final_k_ids"),
        ("MRR", "mrr", "mrr_ids"),
        ("nDCG@5", "ndcg_at_5", "ndcg_at_5_ids"),
    ):
        old = _mean([rows[q].get(old_key) for q in subset])
        new = _mean([rows[q].get(new_key) for q in subset])
        delta = "" if old is None or new is None else f"{new - old:+.4f}"
        print(f"{name:<10}{_fmt(old):<22}{_fmt(new):<20}{delta:<10}")

    diffs = []
    for qid in subset:
        old = rows[qid].get("recall_at_final_k")
        new = rows[qid].get("recall_at_final_k_ids")
        if old is None or new is None:
            continue
        diffs.append((new - old, qid))

    diffs.sort()
    print(f"\n旧口径更乐观（新口径更低）的题：{[q for d, q in diffs if d < 0][:8]}")
    print(f"新口径更乐观（旧口径漏判）的题：{[q for d, q in diffs if d > 0][:8]}")
    both = sum(1 for d, _ in diffs if abs(d) < 1e-9)
    print(f"\n两种口径完全一致的题：{both} / {len(diffs)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="新旧召回口径并排比较")
    parser.add_argument("--report", required=True)
    parser.add_argument("--gold-file", required=True)
    parser.add_argument(
        "--answerable-only",
        action="store_true",
        help="只统计可答题（排除拒答/语料缺失题），用于和排除不可答题的报告对齐",
    )
    args = parser.parse_args(argv)
    return compare(args.report, args.gold_file, answerable_only=args.answerable_only)


if __name__ == "__main__":
    raise SystemExit(main())
