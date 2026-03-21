"""Real Prometheus metrics — re-exports overlapping metrics from tracer.py."""

from __future__ import annotations

from prometheus_client import Counter as _Counter
from prometheus_client import Gauge as _Gauge

from app.observability.tracer import (
    LLM_TOKEN_TOTAL,  # noqa: F401
    RETRIEVAL_CHANNEL_DURATION,  # noqa: F401
    RETRIEVAL_CHANNEL_TOTAL,  # noqa: F401
    RETRIEVAL_EMPTY_TOTAL,  # noqa: F401
)

# Chat subsystem
EXCHANGE_TOTAL = _Counter("exchange_total", "对话完成总数")
EXCHANGE_RATING_TOTAL = _Counter("exchange_rating_total", "对话评分总数", ["rating"])
EXECUTION_MODE_TOTAL = _Counter("execution_mode_total", "执行模式分布", ["mode"])
ACTIVE_EXCHANGES = _Gauge("active_exchanges", "当前活跃对话数")

# LLM subsystem
LLM_FINISH_REASON_TOTAL = _Counter("llm_finish_reason_total", "LLM 结束原因分布", ["model", "reason"])

# Context subsystem
CONTEXT_WINDOW_UTILIZATION = _Gauge("context_window_utilization", "上下文窗口利用率")
CONTEXT_TRUNCATION_TOTAL = _Counter("context_truncation_total", "上下文截断次数", ["reason"])
