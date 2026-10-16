from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel

from app.observability.metrics.base import Metric, MetricResult, parse_json_safe

logger = structlog.get_logger(__name__)

_MAX_CONTEXT_CHARS = 8000


class StatementExtraction(BaseModel):
    statements: list[str]


class NLIResult(BaseModel):
    verdicts: list[int]
    reasons: list[str]


_EXTRACT_PROMPT = """You are analyzing a RAG answer. Break the answer down into individual factual statements.

For each statement:
- Make it atomic (one fact per statement)
- Resolve pronouns to their referents
- Keep the exact meaning from the original answer

Return JSON: {"statements": ["statement 1", "statement 2", ...]}

IMPORTANT: Score based ONLY on semantic meaning and evidence support.
Ignore surface features such as answer length, wording style, citation
format ([1][2] vs (1)(2) vs none), or text formatting. An identical
meaning expressed with more/less verbosity must receive the same score."""

_NLI_PROMPT = """You are judging whether statements are supported by the given context.

For each statement, determine if it can be directly inferred from the context.
Return JSON: {"verdicts": [1, 0, 1, ...], "reasons": ["supported by...", "not found in context", ...]}

Where:
- 1 = statement is supported by the context
- 0 = statement is NOT supported by the context

IMPORTANT: Score based ONLY on semantic meaning and evidence support.
Ignore surface features such as answer length, wording style, citation
format ([1][2] vs (1)(2) vs none), or text formatting. An identical
meaning expressed with more/less verbosity must receive the same score."""


class FaithfulnessMetric(Metric):
    name = "faithfulness"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
        tracer: Any = None,
    ) -> MetricResult:
        if not answer or not contexts:
            return MetricResult(
                metric_name="faithfulness",
                value=0.0,
                reason="empty answer or context",
                metadata={},
            )
        raw = (
            await self._call_llm(
                tracer=tracer,
                name="faithfulness_extract",
                messages=[
                    {"role": "system", "content": _EXTRACT_PROMPT},
                    {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer}"},
                ],
                temperature=0.0,
            )
            or "{}"
        )
        data = parse_json_safe(raw, default={"statements": []})
        try:
            extracted = StatementExtraction(**data)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return MetricResult(
                metric_name="faithfulness", value=0.0, reason="parse error", metadata={}
            )

        if not extracted.statements:
            return MetricResult(
                metric_name="faithfulness", value=1.0, reason="no statements to verify", metadata={}
            )

        context_str = "\n\n".join(contexts)
        if len(context_str) > _MAX_CONTEXT_CHARS:
            context_str = context_str[:_MAX_CONTEXT_CHARS] + "\n\n[...truncated]"

        # JEV System 1 Noul 评测优化（单 pass 并行判定，无需 LLM 自回归与 JSON 反序列化）
        from app.infra.jev_client import jev_decide

        questions = {
            f"stmt_{i}": {
                "type": "noul",
                "instructions": f"以下陈述命题是否能够直接从给定上下文中推断得出（不含推测与无中生有）：\n命题：{s}",
            }
            for i, s in enumerate(extracted.statements)
        }

        def _parse(answers: dict) -> MetricResult:
            if not answers:
                raise ValueError("JEV returned empty answers")
            verdicts = []
            reasons = []
            scores = []
            for i in range(len(extracted.statements)):
                key = f"stmt_{i}"
                res = answers.get(key)
                if not isinstance(res, dict) or "noul" not in res:
                    raise ValueError(f"JEV response missing valid evaluation for {key}")
                prob = float(res.get("noul", 0.0))
                scores.append(prob)
                is_sup = 1 if prob >= 0.50 else 0
                verdicts.append(is_sup)
                reasons.append(f"命题{i + 1}: {'支持' if is_sup else '无支持'}(置信度={prob:.2f})")
            total = len(verdicts)
            supported = sum(verdicts)
            score = supported / total if total > 0 else 1.0
            return MetricResult(
                metric_name="faithfulness",
                value=score,
                reason=" | ".join(reasons[:5]),
                metadata={
                    "total_statements": total,
                    "supported": supported,
                    "scores": scores,
                    "evaluated_by": "jev-system-one",
                },
            )

        jev_result = await jev_decide(
            "faithfulness_eval_enabled",
            state=f"参考上下文证据：\n{context_str}",
            questions=questions,
            parse=_parse,
            log_context="JEV faithfulness eval",
        )
        if jev_result is not None:
            return jev_result

        raw2 = (
            await self._call_llm(
                tracer=tracer,
                name="faithfulness_nli",
                messages=[
                    {"role": "system", "content": _NLI_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Context:\n{context_str}\n\n"
                            f"Statements:\n" + "\n".join(f"- {s}" for s in extracted.statements)
                        ),
                    },
                ],
                temperature=0.0,
            )
            or "{}"
        )
        nli_data = parse_json_safe(raw2, default={"verdicts": [], "reasons": []})
        try:
            nli = NLIResult(**nli_data)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return MetricResult(
                metric_name="faithfulness", value=0.0, reason="NLI parse error", metadata={}
            )

        total = len(nli.verdicts)
        supported = sum(nli.verdicts)
        score = supported / total if total > 0 else 1.0
        return MetricResult(
            metric_name="faithfulness",
            value=score,
            reason=" | ".join(nli.reasons[:5]),
            metadata={"total_statements": total, "supported": supported},
        )
