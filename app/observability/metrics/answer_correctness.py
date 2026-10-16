from __future__ import annotations

from typing import Any

import structlog

from app.observability.metrics.base import Metric, MetricResult

logger = structlog.get_logger(__name__)

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
        tracer: Any = None,
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

        # JEV System 1 Score 原语（等级化事实一致性评分，毫秒级、强类型、无 JSON 解析）
        from app.config import get_settings

        settings = get_settings()
        jev_cfg = getattr(settings, "jev", None)
        if jev_cfg and getattr(jev_cfg, "answer_correctness_enabled", True):
            try:
                from app.infra.jev_client import get_jev_client

                jev = get_jev_client()
                state = (
                    f"【问题】\n{question}\n\n"
                    f"【标准答案】\n{ground_truth}\n\n"
                    f"【待评答案】\n{answer}"
                )
                answers = await jev.system_one(
                    state=state,
                    questions={
                        "correctness": {
                            "type": "score",
                            "instructions": (
                                "评估待评答案与标准答案的事实一致性（是否覆盖关键事实且无矛盾），"
                                "忽略措辞与格式差异"
                            ),
                            "levels": [
                                "完全不一致",
                                "大部分不一致",
                                "部分一致",
                                "基本一致",
                                "完全一致",
                            ],
                        }
                    },
                )
                if not answers:
                    raise ValueError("JEV returned empty answers")

                score_data = answers.get("correctness")
                if not isinstance(score_data, dict) or "score" not in score_data:
                    raise ValueError("JEV response missing valid correctness evaluation")

                level_map = {
                    "完全不一致": 0.0,
                    "大部分不一致": 0.25,
                    "部分一致": 0.50,
                    "基本一致": 0.75,
                    "完全一致": 1.0,
                }
                level = score_data.get("score", "部分一致")
                score = level_map.get(level, 0.50)
                conf = float(score_data.get("confidence", 1.0))
                distribution = (
                    score_data.get("distribution")
                    if isinstance(score_data.get("distribution"), dict)
                    else {}
                )
                return MetricResult(
                    metric_name="answer_correctness",
                    value=score,
                    reason=f"JEV Score: {level} (置信度={conf:.2f})",
                    metadata={
                        "level": level,
                        "confidence": conf,
                        "distribution": distribution,
                        "evaluated_by": "jev-system-one",
                    },
                )
            except Exception as e:
                logger.warning(
                    "JEV answer correctness eval failed, falling back to LLM",
                    error=str(e)[:120],
                )

        content = (
            await self._call_llm(
                tracer=tracer,
                name="answer_correctness",
                messages=[
                    {"role": "system", "content": _PROMPT},
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nAnswer: {answer}\n\nGround Truth: {ground_truth}",
                    },
                ],
                temperature=0.0,
            )
            or "0"
        )
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
