from __future__ import annotations

from typing import Any

import structlog

from app.observability.metrics.base import Metric, MetricResult

logger = structlog.get_logger(__name__)

_PROMPT = """You are evaluating the relevance of an answer to a question.

On a scale from 0 to 100, how relevant is the answer to the question?
- 0 = completely irrelevant (does not address the question at all)
- 100 = perfectly relevant (directly answers the question with no extraneous information)

Return ONLY a number between 0 and 100. No explanation.

IMPORTANT: Score based ONLY on semantic meaning and evidence support.
Ignore surface features such as answer length, wording style, citation
format ([1][2] vs (1)(2) vs none), or text formatting. An identical
meaning expressed with more/less verbosity must receive the same score."""


class AnswerRelevancyMetric(Metric):
    name = "answer_relevancy"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
        tracer: Any = None,
    ) -> MetricResult:
        if not answer or not question:
            return MetricResult(
                metric_name="answer_relevancy",
                value=0.0,
                reason="empty question or answer",
                metadata={},
            )

        # JEV System 1 Score 原语评测（等级化确定性评分与校准置信度）
        from app.infra.jev_client import jev_decide

        def _parse(answers: dict) -> MetricResult:
            if not answers:
                raise ValueError("JEV returned empty answers")
            score_data = answers.get("relevancy")
            if not isinstance(score_data, dict) or "score" not in score_data:
                raise ValueError("JEV response missing valid relevancy evaluation")
            level_map = {
                "完全无关": 0.0,
                "部分相关": 0.25,
                "基本相关": 0.50,
                "高度相关": 0.75,
                "完全切题": 1.0,
            }
            level = score_data.get("score", "基本相关")
            conf = float(score_data.get("confidence", 1.0))
            distribution = (
                score_data.get("distribution")
                if isinstance(score_data.get("distribution"), dict)
                else {}
            )
            if distribution:
                total_prob = 0.0
                weighted_sum = 0.0
                for lvl, w in level_map.items():
                    try:
                        p = float(distribution.get(lvl, 0.0))
                    except (ValueError, TypeError):
                        p = 0.0
                    weighted_sum += p * w
                    total_prob += p
                if total_prob > 0.0:
                    score = round(max(0.0, min(1.0, weighted_sum / total_prob)), 4)
                else:
                    score = level_map.get(level, 0.50)
            else:
                score = level_map.get(level, 0.50)
            return MetricResult(
                metric_name="answer_relevancy",
                value=score,
                reason=f"JEV Score: {level} (期望得分={score:.4f}, 置信度={conf:.2f})",
                metadata={
                    "level": level,
                    "confidence": conf,
                    "distribution": distribution,
                    "evaluated_by": "jev-system-one",
                },
            )

        jev_result = await jev_decide(
            "answer_relevancy_enabled",
            state=f"【用户问题】\n{question}\n\n【系统回答】\n{answer}",
            questions={
                "relevancy": {
                    "type": "score",
                    "instructions": "评估回答对问题的针对性和相关程度（语义相关，忽略表面格式）",
                    "levels": ["完全无关", "部分相关", "基本相关", "高度相关", "完全切题"],
                }
            },
            parse=_parse,
            log_context="JEV answer relevancy eval",
        )
        if jev_result is not None:
            return jev_result

        content = (
            await self._call_llm(
                tracer=tracer,
                name="answer_relevancy",
                messages=[
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer}"},
                ],
                temperature=0.0,
            )
            or "0"
        )
        import re

        score_match = re.search(
            r"(?:score|得分|分数|relevance|rating)[^\d]*(\b100|\b[1-9]?[0-9])\b",
            content,
            re.IGNORECASE,
        )
        if score_match:
            score = int(score_match.group(1)) / 100.0
        else:
            valid_nums = re.findall(r"\b(100|[1-9]?[0-9])\b", content)
            score = int(valid_nums[-1]) / 100.0 if valid_nums else 0.0
        score = max(0.0, min(1.0, score))
        return MetricResult(
            metric_name="answer_relevancy",
            value=score,
            reason=f"LLM scored {score:.2f}",
            metadata={},
        )
