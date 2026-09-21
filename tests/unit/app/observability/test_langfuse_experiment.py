"""Langfuse Experiment：evaluator 包装 + golden experiment 运行测试"""

import pytest

from app.observability.langfuse_experiment import build_evaluators, run_golden_experiment
from app.observability.metrics.base import MetricResult


class _FakeMetric:
    metric_name = "faithfulness"

    def __init__(self):
        self.calls: list[dict] = []

    async def ascore(self, *, question, answer, contexts, ground_truth=None, tracer=None):
        self.calls.append(
            {"question": question, "answer": answer, "contexts": contexts}
        )
        return MetricResult(metric_name="faithfulness", value=0.8, reason="ok")


@pytest.mark.asyncio
async def test_build_evaluators_wraps_metric():
    metric = _FakeMetric()
    evaluators = build_evaluators([metric])
    assert len(evaluators) == 1

    out = await evaluators[0](
        input={"question": "q", "contexts": ["c1", "c2"]},
        output={"answer": "a"},
        expected_output=None,
        metadata=None,
    )

    assert out == {"name": "faithfulness", "value": 0.8, "comment": "ok"}
    assert metric.calls[0] == {
        "question": "q",
        "answer": "a",
        "contexts": ["c1", "c2"],
    }


@pytest.mark.asyncio
async def test_run_golden_experiment_uses_dataset_run_experiment():
    class FakeDataset:
        def __init__(self):
            self.kwargs: dict = {}

        def run_experiment(self, **kwargs):
            self.kwargs = kwargs
            return "RESULT"

    class FakeClient:
        def __init__(self):
            self.dataset = FakeDataset()
            self.requested: str | None = None

        def get_dataset(self, name):
            self.requested = name
            return self.dataset

    client = FakeClient()
    task = object()
    evaluators = [object()]

    result = await run_golden_experiment(
        client, "golden", task=task, evaluators=evaluators, run_name="r1"
    )

    assert result == "RESULT"
    assert client.requested == "golden"
    assert client.dataset.kwargs["task"] is task
    assert client.dataset.kwargs["evaluators"] is evaluators
    assert client.dataset.kwargs["run_name"] == "r1"
