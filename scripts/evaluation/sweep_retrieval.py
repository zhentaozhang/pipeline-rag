"""RRF / 检索参数网格搜索（P1）。

在标注子集上扫描 RRF k 与双通道权重，按检索侧指标（Recall@k、命中率、未召回率）
选优，避免在错误的融合参数上继续调优。使用 `--retrieval-only` 快速通道，不产生
生成与 LLM 评测开销。

用法示例：
    python -m scripts.evaluation.sweep_retrieval \
        --variant v2 --sample-per-category 3 \
        --k-values 2,5,20,60 --weights 1.0,1.0 --weights 0.7,0.3 --weights 0.3,0.7

选出的参数随后应锁定，在完整标注集（held-out）上做最终验证，防止过拟合。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SWEEP_DIR = Path("reports/sweep")


def _parse_weights(raw: str) -> tuple[float, float]:
    parts = raw.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"weights 需形如 '1.0,1.0'，收到 {raw!r}")
    return float(parts[0]), float(parts[1])


def _run_config(
    variant: str,
    sample_per_category: int,
    rrf_k: int,
    v_weight: float,
    k_weight: float,
    concurrency: int,
) -> dict | None:
    _SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{variant}_k{rrf_k}_w{v_weight:g}-{k_weight:g}"
    report_path = _SWEEP_DIR / f"{tag}.json"
    cmd = [
        sys.executable,
        "-m",
        "scripts.evaluation.runner",
        "--variant",
        variant,
        "--round",
        tag,
        "--sample-per-category",
        str(sample_per_category),
        "--concurrency",
        str(concurrency),
        "--retrieval-only",
        "--rrf-k",
        str(rrf_k),
        "--rrf-vector-weight",
        str(v_weight),
        "--rrf-keyword-weight",
        str(k_weight),
        "--min-faithfulness",
        "0",
        "--min-relevancy",
        "0",
        "--min-precision",
        "0",
        "--min-recall",
        "0",
        "--min-correctness",
        "0",
        "--json-report",
        str(report_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[FAIL] {tag}\n{proc.stderr[-800:]}", file=sys.stderr)
        return None
    if not report_path.exists():
        print(f"[FAIL] {tag}: 未生成报告", file=sys.stderr)
        return None
    with open(report_path, encoding="utf-8") as fh:
        data = json.load(fh)
    avg = data.get("averages", {})
    stage = data.get("stage_attribution_summary", {})
    return {
        "tag": tag,
        "rrf_k": rrf_k,
        "v_weight": v_weight,
        "k_weight": k_weight,
        "recall_at_5": avg.get("recall_at_5", 0.0),
        "recall_at_final_k": avg.get("recall_at_final_k", 0.0),
        "eval_depth": data.get("provenance", {}).get("retrieval_eval_depth", 10),
        "hit_rate": stage.get("hit_rate", 0.0),
        "unrecalled_rate": stage.get("unrecalled_rate", 0.0),
        "rerank_demote_rate": stage.get("rerank_demote_rate", 0.0),
        "fusion_drop_rate": stage.get("fusion_drop_rate", 0.0),
        "cutoff_drop_rate": stage.get("cutoff_drop_rate", 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="RRF 检索参数网格搜索 (P1)")
    parser.add_argument("--variant", type=str, default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--sample-per-category", type=int, default=3)
    parser.add_argument("--k-values", type=str, default="2,5,20,60")
    parser.add_argument(
        "--weights",
        type=_parse_weights,
        action="append",
        default=None,
        help="双通道权重 'vector,keyword'，可重复传入多个组合",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    k_values = [int(x) for x in args.k_values.split(",") if x.strip()]
    weight_pairs = args.weights or [(1.0, 1.0)]

    rows: list[dict] = []
    for k in k_values:
        for vw, kw in weight_pairs:
            print(f"[RUN] variant={args.variant} k={k} weight=({vw:g},{kw:g})", flush=True)
            row = _run_config(args.variant, args.sample_per_category, k, vw, kw, args.concurrency)
            if row:
                rows.append(row)

    if not rows:
        print("无有效结果。", file=sys.stderr)
        return 1

    depth = rows[0].get("eval_depth", 10)
    rows.sort(key=lambda r: (r["recall_at_final_k"], r["hit_rate"]), reverse=True)
    header = (
        f"{'config':<20} {'R@5':>6} {f'R@{depth}':>6} {'hit':>6} "
        f"{'unrec':>6} {'demote':>7} {'fusion':>7} {'cutoff':>7}"
    )
    print(f"\n=== RRF 网格搜索结果（按 Recall@{depth} 降序）===")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['tag']:<20} {r['recall_at_5']:>6.3f} {r['recall_at_final_k']:>6.3f} "
            f"{r['hit_rate']:>6.3f} {r['unrecalled_rate']:>6.3f} "
            f"{r['rerank_demote_rate']:>7.3f} {r['fusion_drop_rate']:>7.3f} "
            f"{r['cutoff_drop_rate']:>7.3f}"
        )
    best = rows[0]
    print(
        f"\n建议锁定: --rrf-k {best['rrf_k']} "
        f"--rrf-vector-weight {best['v_weight']:g} "
        f"--rrf-keyword-weight {best['k_weight']:g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
