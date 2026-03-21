from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass
class RetrievalStrategy:
    name: str
    reranker_enabled: bool = True
    top_k: int = 10
    rrf_k: int = 60
    vector_weight: float = 0.5
    keyword_weight: float = 0.5


class EvalSample(BaseModel):
    question: str
    ground_truth: str
    contexts: list[str] = []


class ExperimentReport(BaseModel):
    experiment_name: str
    strategy_results: dict[str, dict[str, float]]  # strategy_name -> metric_name -> avg_score
    winner: str = ""


class Experiment:
    def __init__(
        self,
        name: str,
        strategies: list[RetrievalStrategy],
        eval_pipeline: Any,
        retrieval_fn: Any,
        answer_fn: Callable[[str, list[str]], str] | None = None,
    ) -> None:
        self._name = name
        self._strategies = strategies
        self._pipeline = eval_pipeline
        self._retrieve = retrieval_fn
        self._answer_fn = answer_fn

    async def run(self, dataset: list[EvalSample]) -> ExperimentReport:

        results: dict[str, dict[str, list[float]]] = {}

        for strategy in self._strategies:
            strategy_name = strategy.name
            results[strategy_name] = {}

            for sample in dataset:
                contexts = await self._retrieve(
                    question=sample.question,
                    top_k=strategy.top_k,
                    reranker=strategy.reranker_enabled,
                    rrf_k=strategy.rrf_k,
                )

                answer = self._answer_fn(sample.question, contexts) if self._answer_fn else ""

                metric_results = await self._pipeline.run(
                    question=sample.question,
                    answer=answer,
                    contexts=contexts,
                    ground_truth=sample.ground_truth,
                )

                for mr in metric_results:
                    if mr.metric_name not in results[strategy_name]:
                        results[strategy_name][mr.metric_name] = []
                    results[strategy_name][mr.metric_name].append(mr.value)

        report: dict[str, dict[str, float]] = {}
        best_avg = -1.0
        winner = self._strategies[0].name

        for strategy_name, metrics in results.items():
            report[strategy_name] = {}
            strategy_avg = 0.0
            count = 0
            for metric_name, scores in metrics.items():
                avg = sum(scores) / len(scores) if scores else 0.0
                report[strategy_name][metric_name] = round(avg, 4)
                strategy_avg += avg
                count += 1

            overall = strategy_avg / count if count > 0 else 0.0
            if overall > best_avg:
                best_avg = overall
                winner = strategy_name

        return ExperimentReport(
            experiment_name=self._name,
            strategy_results=report,
            winner=winner,
        )
