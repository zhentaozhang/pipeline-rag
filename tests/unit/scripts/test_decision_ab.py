"""decision_ab（JEV vs 旧方案 P/R/F1）纯逻辑与后端容错单测。"""

from __future__ import annotations

import math

import pytest

from scripts.evaluation.datasets.base import DecisionSample
from scripts.evaluation.datasets.decision_data import (
    CONTEXT_RELEVANCE_DATASET,
    EVIDENCE_SUFFICIENCY_DATASET,
    GUARDRAIL_DATASET,
    QUALITY_DATASET,
)
from scripts.evaluation.decision_ab import (
    BackendResult,
    ConfusionMatrix,
    GuardrailTask,
    build_confusion,
    evaluate_backend,
    render_report,
)


class TestConfusionMatrix:
    def test_counts(self):
        cm = build_confusion([(True, True), (True, False), (False, True), (False, False)])
        assert (cm.tp, cm.fp, cm.fn, cm.tn) == (1, 1, 1, 1)

    def test_metrics_perfect(self):
        cm = ConfusionMatrix(tp=4, fp=0, fn=0, tn=4)
        assert cm.accuracy == 1.0
        assert cm.precision == 1.0
        assert cm.recall == 1.0
        assert cm.f1 == 1.0

    def test_metrics_edge_zero_division(self):
        cm = ConfusionMatrix()
        assert cm.total == 0
        assert cm.accuracy == 0.0
        assert cm.precision == 0.0
        assert cm.recall == 0.0
        assert cm.f1 == 0.0

    def test_recall_positive_prediction_bias(self):
        # 全部判正：recall=1，precision 低
        cm = ConfusionMatrix(tp=5, fp=5, fn=0, tn=0)
        assert cm.recall == 1.0
        assert cm.precision == 0.5
        assert math.isclose(cm.f1, 2 / 3, rel_tol=1e-9)

    def test_known_precision_recall(self):
        cm = ConfusionMatrix(tp=6, fp=2, fn=3, tn=9)
        assert math.isclose(cm.precision, 6 / 8)
        assert math.isclose(cm.recall, 6 / 9)
        assert math.isclose(cm.accuracy, 15 / 20)


def _samples(*labels: bool) -> list[DecisionSample]:
    return [DecisionSample(id=f"s{i}", input="x", label=lab) for i, lab in enumerate(labels)]


class TestEvaluateBackend:
    async def test_verdicts_and_latency(self):
        samples = _samples(True, False, True, False)

        async def predictor(s: DecisionSample) -> BackendResult:
            return BackendResult(verdict=s.label, latency_ms=1.0, detail="ok")

        report = await evaluate_backend("fake", samples, predictor)
        assert report.errors == 0
        assert report.confusion.tp == 2
        assert report.confusion.tn == 2
        assert report.avg_latency_ms == 1.0
        assert report.p95_latency_ms == 1.0

    async def test_raising_predictor_counted_as_error(self):
        samples = _samples(True, False)

        async def predictor(s: DecisionSample) -> BackendResult:
            raise RuntimeError("service down")

        report = await evaluate_backend("fake", samples, predictor)
        assert report.errors == 2
        assert report.confusion.total == 0

    async def test_none_verdict_counted_as_error(self):
        samples = _samples(True, False)

        async def predictor(s: DecisionSample) -> BackendResult:
            return BackendResult(verdict=None, latency_ms=0.5, detail="missing")

        report = await evaluate_backend("fake", samples, predictor)
        assert report.errors == 2
        assert report.confusion.total == 0

    async def test_as_dict_shape(self):
        samples = _samples(True)

        async def predictor(s: DecisionSample) -> BackendResult:
            return BackendResult(verdict=True, latency_ms=2.5)

        report = await evaluate_backend("fake", samples, predictor)
        d = report.as_dict()
        assert d["tp"] == 1 and d["recall"] == 1.0
        assert set(d) >= {"accuracy", "precision", "recall", "f1", "errors", "n"}


class TestDatasets:
    def test_ids_unique_and_labels_bool(self):
        for dataset in (
            CONTEXT_RELEVANCE_DATASET,
            GUARDRAIL_DATASET,
            EVIDENCE_SUFFICIENCY_DATASET,
            QUALITY_DATASET,
        ):
            ids = [s.id for s in dataset]
            assert len(ids) == len(set(ids))
            assert all(isinstance(s.label, bool) for s in dataset)

    def test_both_classes_present(self):
        for dataset in (
            CONTEXT_RELEVANCE_DATASET,
            GUARDRAIL_DATASET,
            EVIDENCE_SUFFICIENCY_DATASET,
            QUALITY_DATASET,
        ):
            labels = {s.label for s in dataset}
            assert labels == {True, False}

    def test_context_relevance_has_context(self):
        assert all(s.context for s in CONTEXT_RELEVANCE_DATASET)
        assert all(s.context for s in EVIDENCE_SUFFICIENCY_DATASET)
        assert all(s.context for s in QUALITY_DATASET)


class TestReport:
    def test_render_report_runs(self):
        task = GuardrailTask()
        report = type(
            "R",
            (),
            {
                "name": "jev",
                "confusion": ConfusionMatrix(tp=1, fp=0, fn=0, tn=1),
                "avg_latency_ms": 5.0,
                "p95_latency_ms": 5.0,
                "errors": 0,
            },
        )()
        text = render_report(task, [report])  # type: ignore[list-item]
        assert "guardrail" in text
        assert "jev" in text


@pytest.mark.asyncio
async def test_run_task_unknown_backend_skipped():
    from scripts.evaluation.decision_ab import run_task

    reports = await run_task(GuardrailTask(), ["does_not_exist"])
    assert reports == []
