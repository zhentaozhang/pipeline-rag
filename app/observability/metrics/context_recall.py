from __future__ import annotations

from app.observability.metrics.base import Metric, MetricResult, parse_json_safe

_EXTRACT_PROMPT = """Break the ground truth answer down into individual factual statements.
Return JSON: {"statements": ["statement 1", "statement 2", ...]}"""

_COVERAGE_PROMPT = """You are checking if statements from the expected answer are covered by the retrieved context.

For each statement, determine if it can be inferred from the context.
Return JSON: {"verdicts": [1, 0, 1, ...], "reasons": ["reason 1", ...]}

Where:
- 1 = statement is supported by the context
- 0 = statement is NOT supported by the context"""


class ContextRecallMetric(Metric):
    name = "context_recall"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> MetricResult:
        if not ground_truth:
            return MetricResult(
                metric_name="context_recall",
                value=0.0,
                reason="ground_truth required for context_recall",
                metadata={},
            )

        resp = self.eval_llm.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user", "content": f"Ground truth: {ground_truth}"},
            ],
            temperature=0.0,
        )
        raw = resp.choices[0].message.content or "{}"
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
        resp2 = self.eval_llm.chat.completions.create(
            model=self.model,
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
        raw2 = resp2.choices[0].message.content or "{}"
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
