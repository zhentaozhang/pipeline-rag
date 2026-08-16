from __future__ import annotations

from app.observability.metrics.base import Metric, MetricResult

_PROMPT = """You are evaluating the correctness of an answer compared to the ground truth.

Rate the answer on a scale from 0 to 100 based on:
- Factual accuracy: does the answer match the ground truth?
- Completeness: does the answer cover the key points from ground truth?
- No hallucinations: the answer should not contain information not in ground truth

Return ONLY a number between 0 and 100. No explanation.

IMPORTANT: Score based ONLY on semantic meaning and evidence support.
Ignore surface features such as answer length, wording style, citation
format ([1][2] vs (1)(2) vs none), or text formatting. An identical
meaning expressed with more/less verbosity must receive the same score."""


class AnswerCorrectnessMetric(Metric):
    name = "answer_correctness"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> MetricResult:
        if not ground_truth:
            return MetricResult(
                metric_name="answer_correctness",
                value=0.0,
                reason="ground_truth required for answer_correctness",
                metadata={},
            )
        if not answer:
            return MetricResult(
                metric_name="answer_correctness",
                value=0.0,
                reason="empty answer",
                metadata={},
            )

        resp = await self.eval_llm.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nAnswer: {answer}\n\nGround Truth: {ground_truth}",
                },
            ],
            temperature=0.0,
        )
        content = resp.choices[0].message.content or "0"
        import re

        match = re.search(r"\d+", content)
        score = int(match.group()) / 100.0 if match else 0.0
        score = max(0.0, min(1.0, score))
        return MetricResult(
            metric_name="answer_correctness",
            value=score,
            reason=f"LLM scored {score:.2f} vs GT",
            metadata={},
        )
