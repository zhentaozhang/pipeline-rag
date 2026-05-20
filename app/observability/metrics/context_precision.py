from __future__ import annotations

from app.observability.metrics.base import Metric, MetricResult, parse_json_safe

_PROMPT = """You are evaluating the relevance of retrieved context chunks for a question.

For each context chunk, determine if it contains information relevant to answering the question.
Return a JSON object with an array of 1 (relevant) or 0 (not relevant) for each chunk.

Example: {"relevance": [1, 0, 1, 1]}"""


class ContextPrecisionMetric(Metric):
    """NOTE: this metric name is misleading — it measures `relevant / total`
    (binary recall), not rank-aware precision as defined in RAGAS."""

    name = "context_precision"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> MetricResult:
        if not contexts:
            return MetricResult(
                metric_name="context_precision",
                value=0.0,
                reason="no contexts",
                metadata={},
            )

        chunks_text = "\n\n---\n\n".join(f"Chunk {i + 1}: {c}" for i, c in enumerate(contexts))
        resp = self.eval_llm.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nContext chunks:\n{chunks_text}",
                },
            ],
            temperature=0.0,
        )
        raw = resp.choices[0].message.content or "{}"
        data = parse_json_safe(raw, default={"relevance": []})
        relevance = data.get("relevance", [])  # type: ignore[union-attr]

        if not relevance:
            return MetricResult(
                metric_name="context_precision", value=0.0, reason="parse error", metadata={}
            )

        total = len(relevance)
        relevant = sum(1 for r in relevance if r == 1)
        score = relevant / total if total > 0 else 0.0
        return MetricResult(
            metric_name="context_precision",
            value=score,
            reason=f"{relevant}/{total} chunks relevant",
            metadata={"total_chunks": total, "relevant_chunks": relevant},
        )
