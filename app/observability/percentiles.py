"""Prometheus Histogram 分位数计算（补齐量化能力 #1）

从进程内 prometheus_client registry 计算 Histogram 的 P50/P90/P99。
数据已由 tracer/metrics_listener 采集（stage/llm/retrieval/exchange 耗时），
此前缺少查询入口（前端表格渲染 p50Ms/p90Ms/p99Ms 但后端端点缺失）。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def _quantile_from_buckets(buckets: list[tuple[float, int]], total: int, q: float) -> float:
    """从累积 bucket (上界, 累积计数) 线性插值分位数（Prometheus histogram_quantile 同思路）"""
    if total <= 0:
        return 0.0
    rank = q * total
    prev_cum = 0
    prev_bound = 0.0
    for bound, cum in buckets:
        if cum >= rank:
            bucket_count = cum - prev_cum  # 桶内计数（累积差）
            if bucket_count <= 0:
                return bound
            frac = (rank - prev_cum) / bucket_count
            return prev_bound + (bound - prev_bound) * frac
        prev_cum = cum
        prev_bound = bound
    return prev_bound


def collect_histogram_quantiles(
    metric_name: str,
    quantiles: tuple[float, ...] = (0.5, 0.9, 0.99),
) -> dict[str, dict[str, float]]:
    """遍历 registry 收集指定 Histogram 的（labels→分位数）映射（单位：秒）。

    返回 {label_key: {q: value_seconds, ...}}；label_key 为逗号拼接的标签值。
    无数据返回空 dict。
    """
    import prometheus_client

    result: dict[str, dict[str, float]] = {}
    try:
        for metric_family in prometheus_client.REGISTRY.collect():
            if metric_family.name != metric_name or metric_family.type != "histogram":
                continue
            # bucket 系列：上界在 labels['le']；count 系列 name 以 _count 结尾
            samples = list(metric_family.samples)  # Sample 对象（name/labels/value 属性）
            series: dict[tuple[str, ...], dict[str, int | float]] = {}
            for sample in samples:
                label_key = tuple(sample.labels.get(k, "") for k in sorted(sample.labels) if k != "le")
                series.setdefault(label_key, {})
                series[label_key][sample.name] = sample.value

            for label_key, samples_dict in series.items():
                buckets: list[tuple[float, int]] = []
                total = 0
                for full_name, value in samples_dict.items():
                    if full_name.endswith("_count"):
                        total = int(value)
                for sample in samples:
                    if sample.name.endswith("_bucket") and tuple(
                        sample.labels.get(k, "") for k in sorted(sample.labels) if k != "le"
                    ) == label_key:
                        le = sample.labels.get("le", "+Inf")
                        if le != "+Inf":
                            buckets.append((float(le), int(sample.value)))
                buckets.sort(key=lambda b: b[0])
                if not buckets or total <= 0:
                    continue
                out: dict[str, float] = {}
                for q in quantiles:
                    out[str(q)] = round(_quantile_from_buckets(buckets, total, q), 4)
                result[",".join(label_key)] = out
    except Exception:
        logger.warning("histogram quantile failed", metric_name=metric_name, exc_info=True)
    return result
