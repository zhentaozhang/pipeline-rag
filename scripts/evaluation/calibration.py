"""评估校准（调研 P4 · SAID 表面混淆检测思路）

目标：验证 LLM-as-Judge 指标是否被"表面特征"污染（答案长度/引用格式/措辞），
而不是真正度量语义与证据支持度。

方法：对同一答案构造表面扰动变体（事实内容不变），跑 6 指标：
  原答案分数 vs 扰动分数 → 一致性 = 1 - |Δ|（越接近 1 越抗表面混淆）
  任一指标平均一致性低于 --min-consistency 时非零退出（门禁）。

用法：
    python -m scripts.evaluation.calibration --samples 3 --min-consistency 0.7

注意：需要评估 LLM 可达（同 runner）；不依赖检索/生成（直接用内置样本）。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field

# ── 表面扰动构造器（纯函数，可单测）────────────────────────────────────────


def verbosity_perturbation(answer: str) -> str:
    """长度扰动：前后加与事实无关的冗余引导/总结语（事实内容不变）"""
    filler_head = "好的，下面我来回答您的问题。根据检索到的资料，可以总结如下："
    filler_tail = "综上所述，以上便是针对该问题的完整回答，希望对您有所帮助。"
    return f"{filler_head}\n{answer}\n{filler_tail}"


def citation_perturbation(answer: str) -> str:
    """引用格式扰动：[1][2] → （1）（2）；无引用则追加说明性引用（事实不变）"""
    converted = re.sub(r"\[(\d+)\]", r"（\1）", answer)
    if "[" not in answer and "（" not in converted or re.search(r"[（(]\d+[)）]", converted):
        return converted
    return converted


# ── 一致性度量（纯函数）────────────────────────────────────────────────────


def consistency_score(original: float, perturbed: float) -> float:
    """扰动一致性：1 - |Δ|（0~1，越接近 1 越抗表面混淆；同分 = 1.0）"""
    return max(0.0, 1.0 - abs(original - perturbed))


@dataclass
class CalibrationSample:
    question: str
    answer: str
    contexts: list[str] = field(default_factory=list)
    ground_truth: str | None = None


_BUILTIN_SAMPLES: list[CalibrationSample] = [
    CalibrationSample(
        question="pipeline-rag 支持哪两种检索通道？",
        answer="支持 PGVector 向量检索与 Elasticsearch 关键词检索双通道，通过 RRF 融合后经 Reranker 精排。[1][2]",
        contexts=["系统采用 PGVector 稠密向量与 Elasticsearch 关键词双通道召回，RRF 融合后由 BGE Reranker 重排序。"],
        ground_truth="PGVector 向量检索 + Elasticsearch 关键词检索，RRF 融合 + Reranker 精排。",
    ),
    CalibrationSample(
        question="Contextual Chunking 解决什么问题？",
        answer="解决分块嵌入时丢失文档上下文的问题：分块时注入文档级上下文窗口，提升跨块实体的检索召回。[1]",
        contexts=["Contextual Chunking 在分块时注入文档级上下文窗口，缓解 chunk 脱离文档语义的问题。"],
        ground_truth="缓解分块丢失文档上下文导致的跨块实体召回差。",
    ),
    CalibrationSample(
        question="长期记忆采用什么策略？",
        answer="默认采用 Summary Compression 结构化摘要压缩 + 滑动窗口，支持长会话的上下文连续性。",
        contexts=["长期记忆提供 Summary Compression 与滑动窗口两种策略，生产推荐摘要压缩。"],
        ground_truth="Summary Compression 摘要压缩与滑动窗口。",
    ),
]


# ── 校准执行 ────────────────────────────────────────────────────────────────


async def run_calibration(
    samples: list[CalibrationSample],
    min_consistency: float,
) -> dict:
    """对样本跑 6 指标 × 扰动，返回逐指标一致性报告"""
    from app.observability.metrics.pipeline import EvaluationPipeline

    pipeline = EvaluationPipeline.with_ground_truth()

    perturb_fns = [
        ("verbosity", verbosity_perturbation),
        ("citation", citation_perturbation),
    ]

    # metric -> {perturb -> [consistency per sample]}
    results: dict[str, dict[str, list[float]]] = {}

    for sample in samples:
        # 原答案基线
        base_results = await pipeline.run(
            question=sample.question,
            answer=sample.answer,
            contexts=sample.contexts,
            ground_truth=sample.ground_truth,
        )
        base_scores = {r.metric_name: r.value for r in base_results}

        for pname, pfn in perturb_fns:
            perturbed = await pipeline.run(
                question=sample.question,
                answer=pfn(sample.answer),
                contexts=sample.contexts,
                ground_truth=sample.ground_truth,
            )
            for r in perturbed:
                orig = base_scores.get(r.metric_name)
                if orig is None:
                    continue
                results.setdefault(r.metric_name, {}).setdefault(pname, []).append(
                    consistency_score(orig, r.value)
                )

    report: dict[str, dict[str, float]] = {}
    for metric, perturbs in results.items():
        report[metric] = {}
        for pname, scores in perturbs.items():
            report[metric][pname] = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {"report": report, "min_consistency": min_consistency}


def _print_report(report: dict[str, dict[str, float]]) -> None:
    print("\n=== 评估指标表面混淆校准报告 ===")
    print(f"{'指标':<22}{'长度扰动':<12}{'引用格式':<12}{'平均':<8}")
    print("-" * 54)
    for metric, perturbs in sorted(report.items()):
        avg = round(sum(perturbs.values()) / max(1, len(perturbs)), 3)
        print(
            f"{metric:<22}"
            f"{perturbs.get('verbosity', 0.0):<12.3f}"
            f"{perturbs.get('citation', 0.0):<12.3f}"
            f"{avg:<8.3f}"
        )
    print("-" * 54)
    print("一致性 = 1 - |原分 - 扰动分|（1.0 = 完全抗表面混淆，越低越敏感）")


async def _main() -> int:
    parser = argparse.ArgumentParser(description="RAG 评估指标表面混淆校准")
    parser.add_argument("--samples", type=int, default=3, help="样本数（默认内置 3 个）")
    parser.add_argument(
        "--min-consistency", type=float, default=0.7, help="门禁：指标平均一致性低于此值则非零退出"
    )
    args = parser.parse_args()

    samples = _BUILTIN_SAMPLES[: args.samples]
    result = await run_calibration(samples, args.min_consistency)
    report = result["report"]
    _print_report(report)

    failed = [
        (m, round(sum(p.values()) / len(p), 3))
        for m, p in report.items()
        if p and sum(p.values()) / len(p) < args.min_consistency
    ]
    if failed:
        print("\n⚠️ 以下指标被表面特征污染（一致性低于阈值）：")
        for m, avg in failed:
            print(f"  - {m}: {avg}")
        return 1
    print("\n✅ 所有指标抗表面混淆一致性与阈值达标")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
