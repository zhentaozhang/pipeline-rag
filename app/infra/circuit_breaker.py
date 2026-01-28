"""
熔断器 Circuit Breaker

为每个外部服务（LLM / ES / PG / Redis）提供独立熔断保护。
状态机：CLOSED → OPEN → (timeout) → HALF_OPEN → CLOSED or OPEN

借鉴 PraisonAI 的 CircuitBreaker 设计模式，专注 async 场景。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import structlog

from app.infra.metrics import (
    CIRCUIT_CALL_TOTAL,
    CIRCUIT_CLOSED_TOTAL,
    CIRCUIT_DURATION,
    CIRCUIT_OPENED_TOTAL,
    CIRCUIT_STATE,
    _state_value,
)
from app.safety.enums import CircuitState

logger = structlog.get_logger(__name__)


@dataclass
class CircuitBreakerConfig:
    """熔断器配置（每个服务独立）"""

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2
    timeout: float = 30.0
    graceful_degradation: bool = True
    fallback: Callable[[], Any] | None = None


class CircuitBreaker:
    """熔断器——async context manager 模式"""

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._start_time = 0.0
        self._lock = asyncio.Lock()
        self._half_open_allowed_count = 0

    # ── 公开属性 ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def state(self) -> CircuitState:
        return self._state

    async def is_available(self) -> bool:
        async with self._lock:
            return self._state != CircuitState.OPEN

    # ── 公开方法 ────────────────────────────────────────────────────────────

    async def record_success(self) -> None:
        """记录一次成功调用"""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._close()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def record_failure(self) -> None:
        """记录一次失败调用"""
        async with self._lock:
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._open()
                return
            self._failure_count += 1
            if self._failure_count >= self._config.failure_threshold:
                self._open()

    # ── async context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> CircuitBreaker:
        allowed = await self._should_allow()
        if not allowed:
            CIRCUIT_CALL_TOTAL.labels(service=self.name, result="rejected").inc()
            if self._config.graceful_degradation and self._config.fallback:
                start = time.monotonic()
                await self._config.fallback()
                self._start_time = start
                CIRCUIT_DURATION.labels(service=self.name, result="fallback").observe(
                    time.monotonic() - start
                )
                CIRCUIT_CALL_TOTAL.labels(service=self.name, result="fallback").inc()
                return self
            msg = f"{self.name} service is unavailable (circuit open)"
            from app.safety.exceptions import CircuitBreakerException

            raise CircuitBreakerException(50301, msg)
        self._start_time = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        elapsed = time.monotonic() - getattr(self, "_start_time", time.monotonic())
        if exc_type is not None:
            if issubclass(exc_type, asyncio.TimeoutError):
                CIRCUIT_CALL_TOTAL.labels(service=self.name, result="timeout").inc()
                CIRCUIT_DURATION.labels(service=self.name, result="timeout").observe(elapsed)
            else:
                CIRCUIT_CALL_TOTAL.labels(service=self.name, result="failure").inc()
                CIRCUIT_DURATION.labels(service=self.name, result="failure").observe(elapsed)
            await self.record_failure()
        else:
            CIRCUIT_CALL_TOTAL.labels(service=self.name, result="success").inc()
            CIRCUIT_DURATION.labels(service=self.name, result="success").observe(elapsed)
            await self.record_success()
        return False

    # ── 内部方法 ────────────────────────────────────────────────────────────

    async def _should_allow(self) -> bool:
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    self._half_open_allowed_count = 1
                    return True
                return False
            # HALF_OPEN: 限制探针数量不超过 success_threshold
            if self._half_open_allowed_count < self._config.success_threshold:
                self._half_open_allowed_count += 1
                return True
            return False

    def _should_attempt_reset(self) -> bool:
        elapsed = time.monotonic() - self._last_failure_time
        return elapsed >= self._config.recovery_timeout

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._half_open_allowed_count = 0
        CIRCUIT_OPENED_TOTAL.labels(service=self.name).inc()
        CIRCUIT_STATE.labels(service=self.name).set(_state_value("open"))
        logger.warning("circuit_breaker_opened", service=self.name)

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_allowed_count = 0
        CIRCUIT_CLOSED_TOTAL.labels(service=self.name).inc()
        CIRCUIT_STATE.labels(service=self.name).set(_state_value("closed"))
        logger.info("circuit_breaker_closed", service=self.name)


class CircuitBreakerRegistry:
    """全局熔断器注册表"""

    _breakers: ClassVar[dict[str, CircuitBreaker]] = {}

    @classmethod
    def get(cls, name: str) -> CircuitBreaker | None:
        return cls._breakers.get(name)

    @classmethod
    def get_or_register(
        cls, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        existing = cls.get(name)
        if existing:
            return existing
        cfg = config or CircuitBreakerConfig(name=name)
        breaker = CircuitBreaker(cfg)
        cls._breakers[name] = breaker
        return breaker

    @classmethod
    def all_states(cls) -> dict[str, CircuitState]:
        return {name: breaker.state for name, breaker in cls._breakers.items()}

    @classmethod
    def reset_all(cls) -> None:
        """重置所有熔断器（用于测试）"""
        cls._breakers.clear()
