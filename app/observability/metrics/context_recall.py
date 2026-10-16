from __future__ import annotations

from typing import Any

import structlog

from app.observability.metrics.base import Metric, MetricResult, parse_json_safe

logger = structlog.get_logger(__name__)

_EXTRACT_PROMPT = """Break the ground truth answer down into individual factual statements.
Return JSON: {"statements": ["statement 1", "statement 2", ...]}"""

_COVERAGE_PROMPT = """You are checking if statements from the expected answer are covered by the retrieved context.

For each statement, determine if it can be inferred from the context.
Return JSON: {"verdicts": [1, 0, 1, ...], "reasons": ["reason 1", ...]}

Where:
- 1 = statement is supported by the context
- 0 = statement is NOT supported by the context

IMPORTANT: Score based ONLY on semantic meaning and evidence support.
Ignore surface features such as answer length, wording style, citation
format ([1][2] vs (1)(2) vs none), or text formatting. An identical
meaning expressed with more/less verbosity must receive the same score."""


class ContextRecallMetric(Metric):
    name = "context_recall"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
        tracer: Any = None,
    ) -> MetricResult:
        if not ground_truth:
            return MetricResult(
                metric_name="context_recall",
                value=0.0,
                reason="ground_truth required for context_recall",
                metadata={},
            )

        raw = (
            await self._call_llm(
                tracer=tracer,
                name="context_recall_extract",
                messages=[
                    {"role": "system", "content": _EXTRACT_PROMPT},
                    {"role": "user", "content": f"Ground truth: {ground_truth}"},
                ],
                temperature=0.0,
            )
            or "{}"
        )
        extracted = parse_json_safe(raw, default={"statements": []})
        statements = extracted.get("statements", [])  # type: ignore[union-attr]

        if not statements:
            return MetricResult(
                metric_name="context_recall",
                value=1.0,
                reason="no statements to verify",
                metadata={},
            )

        context_str = "\n\n".join(contexts) if contexts else ""

        # JEV System 1 并行 Noul 评测优化（替代 LLM 第二阶段 NLI 覆盖判断）
        from app.config import get_settings

        settings = get_settings()
        jev_cfg = getattr(settings, "jev", None)
        if jev_cfg and getattr(jev_cfg, "context_recall_enabled", True):
            try:
                from app.infra.jev_client import get_jev_client

                jev = get_jev_client()
                questions = {
                    f"stmt_{i}": {
                        "type": "noul",
                        "instructions": f"以下标准答案命题是否能从检索到的上下文中直接推断得到：\n命题：{s}",
                    }
                    for i, s in enumerate(statements)
                }
                state = f"检索到的全部上下文：\n{context_str}"
                answers = await jev.system_one(state=state, questions=questions)

                if not answers:
                    raise ValueError("JEV returned empty answers")

                verdicts = []
                reasons = []
                for i in range(len(statements)):
                    key = f"stmt_{i}"
                    res = answers.get(key)
                    if not isinstance(res, dict) or "noul" not in res:
                        raise ValueError(f"JEV response missing valid evaluation for {key}")
                    prob = float(res.get("noul", 0.0))
                    is_cov = 1 if prob >= 0.50 else 0
                    verdicts.append(is_cov)
                    reasons.append(
                        f"命题{i + 1}: {'已覆盖' if is_cov else '未覆盖'}(置信度={prob:.2f})"
                    )

                total = len(verdicts)
                covered = sum(verdicts)
                score = covered / total if total > 0 else 1.0
                return MetricResult(
                    metric_name="context_recall",
                    value=score,
                    reason=" | ".join(reasons[:5]),
                    metadata={
                        "total_statements": total,
                        "covered": covered,
                        "evaluated_by": "jev-system-one",
                    },
                )
            except Exception as e:
                logger.warning(
                    "JEV context recall eval failed, falling back to LLM",
                    error=str(e)[:120],
                )

        raw2 = (
            await self._call_llm(
                tracer=tracer,
                name="context_recall_coverage",
                messages=[
                    {"role": "system", "content": _COVERAGE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Context:\n{context_str}\n\n"
                            f"Statements:\n" + "\n".join(f"- {s}" for s in statements)
                        ),
                    },
                ],
                temperature=0.0,
            )
            or "{}"
        )
        coverage = parse_json_safe(raw2, default={"verdicts": [], "reasons": []})
        verdicts = coverage.get("verdicts", [])  # type: ignore[union-attr]
        reasons = coverage.get("reasons", [])  # type: ignore[union-attr]

        total = len(verdicts)
        covered = sum(verdicts)
        score = covered / total if total > 0 else 1.0
        return MetricResult(
            metric_name="context_recall",
            value=score,
            reason=" | ".join(reasons[:5]),
            metadata={"total_statements": total, "covered": covered},
        )
