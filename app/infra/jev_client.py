"""
JEV System 1 本地服务 Python 客户端
统一封装对 jev-service (或商业 Jev API) 的调用，提供强类型决策接口。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, TypeVar, cast

import httpx
import structlog

from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry
from app.infra.metrics import (
    JEV_CALL_LATENCY_SECONDS,
    JEV_CALL_TOTAL,
    JEV_QUESTIONS_TOTAL,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# JEV 支持的问题类型（限制 label 取值，避免高基数）
_JEV_QUESTION_TYPES = frozenset({"noul", "choice", "score"})

# 为 JEV 决策微服务注册独立熔断器（与 LLM / ES 独立隔离）
# 连续失败 5 次即刻熔断开路，单次硬超时由 10s 放宽至 60s（防御多并发下显存排队等待）
_jev_breaker = CircuitBreakerRegistry.get_or_register(
    "jev",
    CircuitBreakerConfig(
        name="jev",
        failure_threshold=5,
        recovery_timeout=30.0,
        timeout=60.0,
    ),
)


# ── 覆盖率埋点（P0-1）───────────────────────────────────────────────
# 评测里"V3 与 V2 是否有区别"完全取决于 JEV 是否真的做了决策。
# 服务不可达 / 开关关闭时 jev_decide 全部 fail-open 回退，报告上却看不出任何异常，
# 所以这里按 flag 统计 decided / failed / disabled 与调用耗时，供评测报告直接引用。
_COVERAGE: dict[str, dict[str, int]] = {}

# 按请求统计 JEV 调用次数（contextvar 而非全局计数：并发请求互不污染）。
# 一个带引用的 RAG 回答历史上会打 7 次 JEV（见 2026-10-21 审计），这是延迟与成本的直接刻度。
_REQUEST_CALLS: ContextVar[int] = ContextVar("jev_request_calls", default=0)


def reset_request_jev_calls() -> None:
    """在新请求开始时清零（executor/中间件入口调用）。"""
    _REQUEST_CALLS.set(0)


def jev_calls_this_request() -> int:
    """当前请求已发出的 JEV 调用次数。"""
    return int(_REQUEST_CALLS.get() or 0)


_COVERAGE_LATENCIES: dict[str, list[float]] = {}
# 常驻进程里样本只增不裁会无界增长；只保留最近 N 个用于 p50/p95 估计。
_MAX_COVERAGE_LATENCIES: int = 512


def reset_jev_coverage() -> None:
    _COVERAGE.clear()
    _COVERAGE_LATENCIES.clear()


def _bump(flag: str, key: str) -> None:
    stat = _COVERAGE.setdefault(flag, {"decided": 0, "failed": 0, "disabled": 0})
    stat[key] = stat.get(key, 0) + 1


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * min(100.0, max(0.0, pct)) / 100.0
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


def jev_coverage() -> dict[str, Any]:
    """返回按 flag 聚合的决策覆盖情况（供评测报告 / 探针脚本引用）。"""
    flags: dict[str, Any] = {}
    totals = {"decided": 0, "failed": 0, "disabled": 0, "attempted": 0}
    for flag, stat in _COVERAGE.items():
        latencies = _COVERAGE_LATENCIES.get(flag, [])
        flags[flag] = {
            **stat,
            "calls": len(latencies),
            "p50_ms": (
                round(_percentile(latencies, 50), 2) if latencies else None  # type: ignore[arg-type]
            ),
            "p95_ms": (
                round(_percentile(latencies, 95), 2) if latencies else None  # type: ignore[arg-type]
            ),
        }
        for key in ("decided", "failed", "disabled"):
            totals[key] += stat.get(key, 0)
    totals["attempted"] = totals["decided"] + totals["failed"]
    return {"flags": flags, "totals": totals}


class JEVClient:
    def __init__(self) -> None:
        settings = get_settings()
        jev_cfg = getattr(settings, "jev", None)
        raw_url = (
            (getattr(jev_cfg, "base_url", None) or "http://localhost:8085").strip().rstrip("/")
        )
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"http://{raw_url}"
        self._base_url = raw_url
        self._timeout = max(1.0, float(getattr(jev_cfg, "timeout_seconds", 60.0) or 60.0))
        self._client: httpx.AsyncClient | None = None
        self._loop: Any = None

    @property
    def base_url(self) -> str:
        settings = get_settings()
        jev_cfg = getattr(settings, "jev", None)
        raw_url = (
            (getattr(jev_cfg, "base_url", None) or self._base_url or "http://localhost:8085")
            .strip()
            .rstrip("/")
        )
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"http://{raw_url}"
        return raw_url

    def _get_client(self) -> httpx.AsyncClient:
        try:
            import asyncio

            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if (
            self._client is None
            or self._client.is_closed
            or (self._loop is not None and current_loop is not None and self._loop != current_loop)
        ):
            self._loop = current_loop
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            self._loop = None

    async def system_one(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        """
        调用 System One 决策端点（受熔断器保护）。
        :param state: 待评估的应用上下文文本
        :param questions: 问题字典 {question_name: {"type": ..., "instructions": ..., ...}}
        :return: answers 结果字典
        """
        if not questions:
            JEV_CALL_TOTAL.labels(outcome="empty").inc()
            return {}

        _REQUEST_CALLS.set(_REQUEST_CALLS.get() + 1)
        url = f"{self.base_url}/v1/systemone"
        payload = {
            "model": "jev-local",
            "state": state,
            "questions": questions,
        }
        t0 = time.perf_counter()
        try:
            async with _jev_breaker:
                client = self._get_client()
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                answers = data.get("answers", {})
        except Exception:
            JEV_CALL_TOTAL.labels(outcome="error").inc()
            raise

        JEV_CALL_LATENCY_SECONDS.observe(time.perf_counter() - t0)
        JEV_CALL_TOTAL.labels(outcome="success").inc()
        for question in questions.values():
            qtype = question.get("type") if isinstance(question, dict) else None
            if qtype in _JEV_QUESTION_TYPES:
                JEV_QUESTIONS_TOTAL.labels(type=qtype).inc()

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "jev_decision_executed",
            question_count=len(questions),
            elapsed_ms=round(elapsed_ms, 2),
        )
        return cast(dict[str, Any], answers) if isinstance(answers, dict) else {}


_jev_client: JEVClient | None = None


def get_jev_client() -> JEVClient:
    global _jev_client
    if _jev_client is None:
        _jev_client = JEVClient()
    return _jev_client


async def jev_decide(
    flag: str,
    state: str,
    questions: dict[str, Any],
    parse: Callable[[dict[str, Any]], T],
    *,
    extra_enabled: bool = True,
    log_context: str = "JEV",
) -> T | None:
    """统一 JEV 决策入口：开关判定 + 调用 + 解析 + 异常回退，消除各调用点重复样板。

    返回 ``parse(answers)`` 的结果；以下情况记录 warning 并返回 ``None``（调用方据此走
    原有 LLM/规则路径，绝不中断主流程）：
    - ``settings.jev.<flag>`` 为假（或 settings 不可用）；
    - ``extra_enabled`` 为假（调用方附加开关，如 safety 侧的护栏开关）；
    - 客户端调用或 ``parse`` 抛任何异常（服务不可达、熔断、响应不完整等）。

    注意：``parse`` 需自行校验 answers 完整性并在不满足时抛错——抛错即触发回退。
    """
    try:
        jev_cfg = getattr(get_settings(), "jev", None)
        enabled = bool(jev_cfg) and bool(getattr(jev_cfg, flag, True)) and extra_enabled
    except Exception:  # noqa: BLE001 — 配置不可用按关闭处理
        enabled = False
    if not enabled:
        _bump(flag, "disabled")
        return None

    t0 = time.perf_counter()
    try:
        answers = await get_jev_client().system_one(state=state, questions=questions)
        parsed = parse(answers)
    except Exception as e:  # noqa: BLE001 — 任何失败都回退到原路径
        _bump(flag, "failed")
        logger.warning(f"{log_context} failed, falling back", error=str(e)[:120])
        return None
    samples = _COVERAGE_LATENCIES.setdefault(flag, [])
    samples.append((time.perf_counter() - t0) * 1000)
    if len(samples) > _MAX_COVERAGE_LATENCIES:
        del samples[: len(samples) - _MAX_COVERAGE_LATENCIES]
    _bump(flag, "decided")
    return parsed
