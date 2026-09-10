"""Langfuse Experiment：把 golden dataset 跑过 RAG 管线并用自实现 metric 打分

- build_evaluators：把 RAG metric 列表包成 Langfuse evaluator 函数
- build_standard_evaluators：构造标准三指标（faithfulness/relevancy/precision）
- make_golden_task：构造 experiment task（按 question+contexts 生成答案）
- run_golden_experiment：在 Langfuse Dataset 上运行 Experiment
"""

from __future__ import annotations

import inspect
from typing import Any


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_evaluators(metrics: list[Any]) -> list[Any]:
    """把 metric 列表包成 Langfuse evaluator 函数（返回 name/value/comment）。"""

    def _make(metric: Any):
        async def _evaluator(
            *,
            input: Any = None,
            output: Any = None,
            expected_output: Any = None,
            metadata: Any = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            question = _get(input, "question", "") or ""
            contexts = _get(input, "contexts", []) or []
            answer = _get(output, "answer", "") if isinstance(output, dict) else (output or "")
            result = await metric.ascore(
                question=str(question),
                answer=str(answer),
                contexts=list(contexts),
            )
            return {
                "name": result.metric_name,
                "value": result.value,
                "comment": result.reason,
            }

        return _evaluator

    return [_make(m) for m in metrics]


def build_standard_evaluators(eval_llm: Any, model: str) -> list[Any]:
    """构造标准 RAG 评估器（faithfulness / answer_relevancy / context_precision）。"""
    from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric
    from app.observability.metrics.context_precision import ContextPrecisionMetric
    from app.observability.metrics.faithfulness import FaithfulnessMetric

    return build_evaluators(
        [
            FaithfulnessMetric(eval_llm=eval_llm, model=model),
            AnswerRelevancyMetric(eval_llm=eval_llm, model=model),
            ContextPrecisionMetric(eval_llm=eval_llm, model=model),
        ]
    )


def make_golden_task(eval_llm: Any, model: str) -> Any:
    """构造 experiment task：按 item 的 question+contexts 生成答案。"""

    async def _task(*, item: Any = None, **kwargs: Any) -> dict[str, Any]:
        inp = _get(item, "input", {}) or {}
        question = _get(inp, "question", "") or ""
        contexts = _get(inp, "contexts", []) or []
        context_text = "\n\n".join(str(c) for c in contexts)
        resp = await eval_llm.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "请根据提供的上下文回答用户的问题。如果上下文中没有包含足够的信息，请声明无法完全解答。",
                },
                {"role": "user", "content": f"问题：{question}\n\n上下文：\n{context_text}"},
            ],
            temperature=0.0,
        )
        answer = resp.choices[0].message.content or ""
        return {"answer": answer, "question": question, "contexts": list(contexts)}

    return _task


async def run_golden_experiment(
    client: Any,
    dataset_name: str,
    *,
    task: Any,
    evaluators: list[Any] | None = None,
    name: str | None = None,
    run_name: str | None = None,
    description: str | None = None,
) -> Any:
    """在 Langfuse Dataset 上运行 Experiment（返回 ExperimentResult）。"""
    dataset = client.get_dataset(dataset_name)
    result = dataset.run_experiment(
        name=name or f"golden-{dataset_name}",
        run_name=run_name,
        description=description,
        task=task,
        evaluators=evaluators or [],
    )
    # langfuse 在同步/异步上下文下可能出现返回 coroutine 的情况，兼容两者
    if inspect.isawaitable(result):
        result = await result
    return result
