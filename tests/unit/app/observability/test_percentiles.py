"""量化能力 #1：Prometheus Histogram 分位数计算"""

import prometheus_client as pc
import pytest

from app.observability.percentiles import _quantile_from_buckets, collect_histogram_quantiles


def test_quantile_from_buckets():
    buckets = [(0.5, 2), (1.0, 4), (2.5, 4)]
    # p50: rank=2 → 桶 0.5 边界
    assert _quantile_from_buckets(buckets, 4, 0.5) == 0.5
    # p90: rank=3.6 → 桶 (0.5, 1.0] 内插值: prev=0.5 + (1.0-0.5)*((3.6-2)/2) = 0.9
    assert _quantile_from_buckets(buckets, 4, 0.9) == pytest.approx(0.9)
    # 空数据
    assert _quantile_from_buckets(buckets, 0, 0.9) == 0.0


def test_collect_histogram_quantiles_real():
    h = pc.Histogram("pct_test_dur", "d", ["kind"])
    h.labels(kind="pipeline").observe(0.5)
    h.labels(kind="pipeline").observe(0.6)
    h.labels(kind="pipeline").observe(1.5)
    r = collect_histogram_quantiles("pct_test_dur")
    assert "pipeline" in r
    p = r["pipeline"]
    assert p["0.5"] <= p["0.9"] <= p["0.99"]
    assert p["0.99"] >= 0.5  # 大值样本被覆盖


def test_missing_metric_returns_empty():
    assert collect_histogram_quantiles("pct_no_such_metric") == {}
