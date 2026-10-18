"""
JEV System 1 本地服务 Python 客户端
统一封装对 jev-service (或商业 Jev API) 的调用，提供强类型决策接口。
"""

from __future__ import annotations

import time
from collections.abc import Callable
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
        return None

    try:
        answers = await get_jev_client().system_one(state=state, questions=questions)
        return parse(answers)
    except Exception as e:  # noqa: BLE001 — 任何失败都回退到原路径
        logger.warning(f"{log_context} failed, falling back", error=str(e)[:120])
        return None
