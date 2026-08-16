"""P4 · 评估校准：扰动构造器 + 一致性度量（SAID 表面混淆检测思路）"""

import pytest

from scripts.evaluation.calibration import (
    citation_perturbation,
    consistency_score,
    verbosity_perturbation,
)


def test_verbosity_perturbation_keeps_facts():
    answer = "系统支持双通道检索。"
    perturbed = verbosity_perturbation(answer)
    assert "双通道检索" in perturbed  # 事实保留
    assert len(perturbed) > len(answer)  # 确实变长
    # 冗余语不改变事实内容（只加引导/总结）
    assert perturbed.startswith("好的，下面我来回答")


def test_citation_perturbation_converts_brackets():
    assert citation_perturbation("答案是 X。[1][2]") == "答案是 X。（1）（2）"
    # 无引用 → 原样返回
    assert citation_perturbation("答案是 X。") == "答案是 X。"
    # 混合格式
    assert citation_perturbation("答案[1]和[2]合并") == "答案（1）和（2）合并"


def test_consistency_score():
    assert consistency_score(0.9, 0.9) == pytest.approx(1.0)  # 完全一致 = 抗混淆
    assert consistency_score(0.9, 0.5) == pytest.approx(0.6)  # 0.4 差距 → 0.6
    assert consistency_score(0.0, 1.0) == pytest.approx(0.0)  # 满分差异 → 0
    assert consistency_score(0.8, 0.0) == pytest.approx(0.2)  # 不越界为负


@pytest.mark.asyncio
async def test_run_calibration_uses_pipeline(monkeypatch):
    """校准执行：mock pipeline → 返回逐指标一致性报告结构"""
    from scripts.evaluation.calibration import (
        CalibrationSample,
        run_calibration,
    )

    class _FakeMetricResult:
        def __init__(self, name, value):
            self.metric_name = name
            self.value = value

    class _FakePipeline:
        async def run(self, **kwargs):
            # 长度扰动版本得分略降（模拟轻微敏感）；其余同分
            if "好的，下面我来回答" in kwargs["answer"]:
                return [
                    _FakeMetricResult("faithfulness", 0.90),
                    _FakeMetricResult("answer_relevancy", 0.85),
                ]
            return [
                _FakeMetricResult("faithfulness", 0.90),
                _FakeMetricResult("answer_relevancy", 0.95),
            ]

    import app.observability.metrics.pipeline as _pipeline_mod

    class _FakeEvaluationPipeline:
        @classmethod
        def with_ground_truth(cls):
            return _FakePipeline()

    monkeypatch.setattr(
        _pipeline_mod, "EvaluationPipeline", _FakeEvaluationPipeline
    )

    samples = [
        CalibrationSample(question="q", answer="答案 A。[1]", contexts=["ctx"], ground_truth="gt")
    ]
    result = await run_calibration(samples, min_consistency=0.7)

    report = result["report"]
    assert "faithfulness" in report
    assert "verbosity" in report["faithfulness"]
    # faithfulness 同分 → 一致性 1.0；relevancy 0.9 vs 0.95 → 0.95
    assert report["faithfulness"]["verbosity"] == pytest.approx(1.0)
    assert report["answer_relevancy"]["verbosity"] == pytest.approx(0.90)
