from __future__ import annotations

from typing import Any

import structlog

from app.observability.metrics.base import Metric, MetricResult, parse_json_safe

logger = structlog.get_logger(__name__)

_PROMPT = """You are evaluating the relevance of retrieved context chunks for a question.

For each context chunk, determine if it contains information relevant to answering the question.
Return a JSON object with an array of 1 (relevant) or 0 (not relevant) for each chunk.

Example: {"relevance": [1, 0, 1, 1]}

IMPORTANT: Score based ONLY on semantic meaning and evidence support.
Ignore surface features such as answer length, wording style, citation
format ([1][2] vs (1)(2) vs none), or text formatting. An identical
meaning expressed with more/less verbosity must receive the same score."""


def compute_rank_aware_context_precision(relevance: list[Any]) -> float:
    """计算符合 RAGAS 学术标准的 Rank-Aware Average Precision (AP@K)

    公式：
        ContextPrecision@K = \\sum_{k=1}^K (Precision@k * v_k) / Total_Relevant_Items
    其中：
        Precision@k = (前 k 个候选块中相关的数量) / k
        v_k 为二值指示变量 (1 为相关，0 为不相关)
    """
    if not relevance:
        return 0.0
    normalized = [
        1 if (r == 1 or r is True or str(r).strip().lower() in ("1", "true")) else 0
        for r in relevance
    ]
    total_relevant = sum(normalized)
    if total_relevant == 0:
        return 0.0

    cum_relevant = 0
    precision_sum = 0.0
    for k, rel in enumerate(normalized, start=1):
        if rel == 1:
            cum_relevant += 1
            precision_sum += cum_relevant / k

    return round(precision_sum / total_relevant, 4)


class ContextPrecisionMetric(Metric):
    """学术标准 RAGAS Context Precision (Rank-Aware AP@K) 指标。
    准确衡量高相关检索证据是否排在前面，能有效评估 Reranker 重排有效性。
    """

    name = "context_precision"

    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
        tracer: Any = None,
    ) -> MetricResult:
        if not contexts:
            return MetricResult(
                metric_name="context_precision",
                value=0.0,
                reason="no contexts",
                metadata={},
            )

        # JEV System 1 并行 Noul 评测优化（单 pass 评估全部检索块相关性）
        from app.infra.jev_client import jev_decide

        questions = {
            f"chunk_{i}": {
                "type": "noul",
                "instructions": (
                    f"该证据片段是否包含有助于回答以下问题的事实信息？\n"
                    f"问题：{question}\n"
                    f"片段内容：{c[:280]}"
                ),
            }
            for i, c in enumerate(contexts)
        }

        def _parse(answers: dict) -> MetricResult:
            if not answers:
                raise ValueError("JEV returned empty answers")
            threshold = 0.50
            relevance = []
            scores = []
            for i in range(len(contexts)):
                key = f"chunk_{i}"
                res = answers.get(key)
                if not isinstance(res, dict) or "noul" not in res:
                    raise ValueError(f"JEV response missing valid evaluation for {key}")
                prob = float(res.get("noul", 0.0))
                scores.append(prob)
                relevance.append(1 if prob >= threshold else 0)
            total = len(relevance)
            relevant = sum(relevance)
            score = compute_rank_aware_context_precision(relevance)
            return MetricResult(
                metric_name="context_precision",
                value=score,
                reason=f"JEV: AP@K={score:.4f} ({relevant}/{total} chunks relevant)",
                metadata={
                    "total_chunks": total,
                    "relevant_chunks": relevant,
                    "scores": scores,
                    "evaluated_by": "jev-system-one",
                },
            )

        jev_result = await jev_decide(
            "context_precision_enabled",
            state=f"用户目标问题：{question}",
            questions=questions,
            parse=_parse,
            log_context="JEV context precision eval",
        )
        if jev_result is not None:
            return jev_result

        chunks_text = "\n\n---\n\n".join(f"Chunk {i + 1}: {c}" for i, c in enumerate(contexts))
        raw = (
            await self._call_llm(
                tracer=tracer,
                name="context_precision",
                messages=[
                    {"role": "system", "content": _PROMPT},
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nContext chunks:\n{chunks_text}",
                    },
                ],
                temperature=0.0,
            )
            or "{}"
        )
        data = parse_json_safe(raw, default={"relevance": []})
        relevance = data.get("relevance", [])  # type: ignore[union-attr]

        if not relevance:
            return MetricResult(
                metric_name="context_precision", value=0.0, reason="parse error", metadata={}
            )

        total = len(relevance)
        rel_binary = [
            1 if (r == 1 or r is True or str(r).strip().lower() in ("1", "true")) else 0
            for r in relevance
        ]
        relevant = sum(rel_binary)
        score = compute_rank_aware_context_precision(rel_binary)
        return MetricResult(
            metric_name="context_precision",
            value=score,
            reason=f"AP@K={score:.4f} ({relevant}/{total} chunks relevant)",
            metadata={"total_chunks": total, "relevant_chunks": relevant},
        )
