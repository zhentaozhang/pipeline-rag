"""
安全层 Prometheus 指标

所有 counter/gauge/histogram 集中定义，避免全局变量散落各处。
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── 命名空间 ───────────────────────────────────────────────────────────────

NAMESPACE = "safety"


# ── L1 输入安全指标 ─────────────────────────────────────────────────────────

INPUT_INJECTION_DETECTED = Counter(
    name="input_injection_detected_total",
    namespace=NAMESPACE,
    subsystem="input",
    documentation="注入检测命中次数（按风险等级分类）",
    labelnames=["risk_level"],
)

INPUT_PII_DETECTED = Counter(
    name="input_pii_detected_total",
    namespace=NAMESPACE,
    subsystem="input",
    documentation="PII 检测命中次数（按 PII 类型分类）",
    labelnames=["pii_type"],
)

INPUT_PII_ANONYMIZED = Counter(
    name="input_pii_anonymized_total",
    namespace=NAMESPACE,
    subsystem="input",
    documentation="PII 脱敏次数",
    labelnames=["pii_type"],
)

INPUT_BLOCKED = Counter(
    name="input_blocked_total",
    namespace=NAMESPACE,
    subsystem="input",
    documentation="输入安全规则拦截次数",
    labelnames=["reason"],
)

INPUT_PASSED = Counter(
    name="input_passed_total",
    namespace=NAMESPACE,
    subsystem="input",
    documentation="输入安全规则通过次数",
)

INPUT_MODE = Gauge(
    name="input_mode",
    namespace=NAMESPACE,
    subsystem="input",
    documentation="当前输入安全模式（0=monitor, 1=fail_open, 2=fail_close）",
)


# ── L2 工具准入指标 ──────────────────────────────────────────────────────────

TOOL_CALL_TOTAL = Counter(
    name="tool_call_total",
    namespace=NAMESPACE,
    subsystem="tool",
    documentation="工具调用总次数（按工具名和审批结果分类）",
    labelnames=["tool_name", "approved"],
)

TOOL_APPROVAL_DURATION = Histogram(
    name="tool_approval_duration_seconds",
    namespace=NAMESPACE,
    subsystem="tool",
    documentation="工具审批耗时分布",
    labelnames=["tool_name"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)


# ── L3 输出安全指标 ──────────────────────────────────────────────────────────

OUTPUT_BLOCKED = Counter(
    name="output_blocked_total",
    namespace=NAMESPACE,
    subsystem="output",
    documentation="输出安全规则拦截次数（按原因分类）",
    labelnames=["reason"],
)

OUTPUT_PASSED = Counter(
    name="output_passed_total",
    namespace=NAMESPACE,
    subsystem="output",
    documentation="输出安全规则通过次数",
)


# ── L4 熔断器指标 ────────────────────────────────────────────────────────────

CIRCUIT_STATE = Gauge(
    name="circuit_state",
    namespace=NAMESPACE,
    subsystem="circuit_breaker",
    documentation="熔断器当前状态（0=closed, 1=half_open, 2=open）",
    labelnames=["service"],
)

CIRCUIT_OPENED_TOTAL = Counter(
    name="circuit_opened_total",
    namespace=NAMESPACE,
    subsystem="circuit_breaker",
    documentation="熔断器打开次数",
    labelnames=["service"],
)

CIRCUIT_CLOSED_TOTAL = Counter(
    name="circuit_closed_total",
    namespace=NAMESPACE,
    subsystem="circuit_breaker",
    documentation="熔断器关闭次数",
    labelnames=["service"],
)

CIRCUIT_CALL_TOTAL = Counter(
    name="circuit_call_total",
    namespace=NAMESPACE,
    subsystem="circuit_breaker",
    documentation="熔断器调用次数（按结果分类）",
    labelnames=["service", "result"],  # success | failure | rejected | timeout | fallback
)

CIRCUIT_DURATION = Histogram(
    name="circuit_call_duration_seconds",
    namespace=NAMESPACE,
    subsystem="circuit_breaker",
    documentation="熔断器内调用耗时",
    labelnames=["service", "result"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)


# ── L5 限流器指标 ────────────────────────────────────────────────────────────

RATE_LIMIT_HITS_TOTAL = Counter(
    name="rate_limit_hits_total",
    namespace=NAMESPACE,
    subsystem="rate_limiter",
    documentation="限流命中次数（按路由组分类）",
    labelnames=["group"],
)


def _state_value(state_str: str) -> int:
    """熔断器状态 → Prometheus gauge 数值"""
    return {"closed": 0, "half_open": 1, "open": 2}.get(state_str, 0)
