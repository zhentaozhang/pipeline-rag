from __future__ import annotations

from app.observability.metrics.base import Metric, MetricResult

_PROMPT = """You are evaluating the relevance of an answer to a question.

On a scale from 0 to 100, how relevant is the answer to the question?
- 0 = completely irrelevant (does not address the question at all)
- 100 = perfectly relevant (directly answers the question with no extraneous information)

Return ONLY a number between 0 and 100. No explanation."""


class AnswerRelevancyMetric(Metric):
    name = "answer_relevancy"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> MetricResult:
        if not answer or not question:
            return MetricResult(
                metric_name="answer_relevancy",
                value=0.0,
                reason="empty question or answer",
                metadata={},
            )

        resp = self.eval_llm.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer}"},
            ],
            temperature=0.0,
        )
        content = resp.choices[0].message.content or "0"
        import re

        match = re.search(r"\d+", content)
        score = int(match.group()) / 100.0 if match else 0.0
        score = max(0.0, min(1.0, score))
        return MetricResult(
            metric_name="answer_relevancy",
            value=score,
            reason=f"LLM scored {score:.2f}",
            metadata={},
        )
