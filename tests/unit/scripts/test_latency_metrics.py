"""延迟聚合（P0-3）：分位数必须是确定性的、可解释的，且不能把 0/None 混进均值。

为什么单测这一层：V3 的主张是"质量非劣 + 延迟更低"，如果 p95 算错，
整个三档评测的核心结论就是错的——而这类纯函数错误在端到端跑里看不出来。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.evaluation.metrics import percentile
from scripts.evaluation.runner import _latency_block


class TestPercentile:
    def test_empty_returns_none(self):
        assert percentile([], 50) is None

    def test_single_value_every_percentile_is_that_value(self):
        assert percentile([123.0], 0) == 123.0
        assert percentile([123.0], 50) == 123.0
        assert percentile([123.0], 100) == 123.0

    def test_p50_of_even_sample_is_mean_of_middle(self):
        assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5

    def test_p50_of_odd_sample_is_middle(self):
        assert percentile([3.0, 1.0, 2.0], 50) == 2.0

    def test_p0_and_p100_are_bounds(self):
        values = [5.0, 1.0, 9.0, 3.0]
        assert percentile(values, 0) == 1.0
        assert percentile(values, 100) == 9.0

    def test_p95_interpolates(self):
        # 20 个点：index = (20-1)*0.95 = 18.05 → v[18] + 0.05*(v[19]-v[18])
        values = [float(i) for i in range(1, 21)]
        assert percentile(values, 95) == pytest.approx(19.05)

    def test_out_of_range_p_is_clamped(self):
        values = [1.0, 2.0, 3.0]
        assert percentile(values, -10) == 1.0
        assert percentile(values, 250) == 3.0

    def test_accepts_unsorted_input(self):
        assert percentile([9.0, 1.0, 5.0], 50) == 5.0


def _r(total_ms=None, retrieval_ms=None, generation_ms=None, status="completed"):
    return SimpleNamespace(
        status=status,
        total_ms=total_ms,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
    )


class TestLatencyBlock:
    def test_reports_p50_and_p95_per_stage(self):
        block = _latency_block(
            [
                _r(total_ms=100.0, retrieval_ms=40.0, generation_ms=60.0),
                _r(total_ms=200.0, retrieval_ms=80.0, generation_ms=120.0),
                _r(total_ms=300.0, retrieval_ms=120.0, generation_ms=180.0),
            ]
        )
        assert block["latency_total_p50_ms"] == pytest.approx(200.0)
        assert block["latency_total_p95_ms"] == pytest.approx(290.0)
        assert block["latency_retrieval_p50_ms"] == pytest.approx(80.0)
        assert block["latency_generation_p50_ms"] == pytest.approx(120.0)
        assert block["latency_samples"] == 3

    def test_missing_stage_is_excluded_not_zeroed(self):
        """retrieval-only 跑没有 generation_ms：不能把它当 0 拉低均值。"""
        block = _latency_block(
            [
                _r(total_ms=100.0, retrieval_ms=40.0, generation_ms=None),
                _r(total_ms=120.0, retrieval_ms=None, generation_ms=None),
            ]
        )
        assert block["latency_retrieval_samples"] == 1
        assert block["latency_generation_p50_ms"] is None
        assert block["latency_generation_samples"] == 0

    def test_skips_non_completed(self):
        block = _latency_block([_r(total_ms=999.0), _r(total_ms=100.0, status="failed")])
        assert block["latency_samples"] == 1
        assert block["latency_total_p50_ms"] == pytest.approx(999.0)

    def test_all_empty_returns_none_fields(self):
        block = _latency_block([])
        assert block["latency_samples"] == 0
        assert block["latency_total_p50_ms"] is None
        assert block["latency_total_p95_ms"] is None
