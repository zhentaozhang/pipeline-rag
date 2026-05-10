from __future__ import annotations

from scripts.evaluation.datasets.base import EvalResult


def _avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _fmt(v: float | None, digits: int = 4) -> str:
    if v is None:
        return "  N/A  "
    return f"{v:.{digits}f}"


def generate_console_report(results: list[EvalResult]) -> str:
    """生成控制台格式的评估报告"""
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status != "completed"]
    total = len(results)

    lines: list[str] = [
        "=" * 72,
        "  RAG 离线评估报告",
        "=" * 72,
        f"  总测试数: {total}  |  完成: {len(completed)}  |  失败: {len(failed)}",
    ]

    if failed:
        lines.append("")
        lines.append("  ── 失败详情 ──")
        for r in failed:
            lines.append(f"    [{r.question_id}] {r.question[:50]} → {r.error}")

    if completed:
        f_scores = [r.faithfulness_score for r in completed]
        ar_scores = [r.answer_relevancy_score for r in completed]
        cp_scores = [r.context_precision_score for r in completed]
        ac_scores = [r.answer_correctness_score for r in completed]
        cr_scores = [r.context_recall_score for r in completed]

        lines.append("")
        lines.append("  ── 平均分 ──")
        lines.append(f"    Faithfulness:        {_fmt(_avg(f_scores))}")
        lines.append(f"    Answer Relevancy:    {_fmt(_avg(ar_scores))}")
        lines.append(f"    Context Precision:   {_fmt(_avg(cp_scores))}")
        lines.append(f"    Answer Correctness:  {_fmt(_avg(ac_scores))}")
        lines.append(f"    Context Recall:      {_fmt(_avg(cr_scores))}")

        avg_retrieval = _avg([r.retrieval_ms for r in completed])
        avg_gen = _avg([r.generation_ms for r in completed])
        avg_total = _avg([r.total_ms for r in completed])
        lines.append("")
        lines.append("  ── 性能 ──")
        lines.append(f"    检索耗时:    {_fmt(avg_retrieval, 0)} ms")
        lines.append(f"    生成耗时:    {_fmt(avg_gen, 0)} ms")
        lines.append(f"    总计耗时:    {_fmt(avg_total, 0)} ms")

        lines.append("")
        lines.append("  ── 逐条明细 ──")
        header = f"  {'ID':8s} {'Fth':6s} {'Rel':6s} {'Prec':6s} {'Corr':6s} {'Rec':6s}  Question"
        lines.append(header)
        lines.append("  " + "-" * len(header))
        for r in completed:
            lines.append(
                f"  {r.question_id:8s}"
                f" {_fmt(r.faithfulness_score):>6s}"
                f" {_fmt(r.answer_relevancy_score):>6s}"
                f" {_fmt(r.context_precision_score):>6s}"
                f" {_fmt(r.answer_correctness_score):>6s}"
                f" {_fmt(r.context_recall_score):>6s}"
                f"  {r.question[:40]}"
            )

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)
