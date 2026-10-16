import pytest

from app.infra.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from app.safety.exceptions import CircuitBreakerException


@pytest.mark.asyncio
async def test_circuit_breaker_context_manager_blocks_body_on_fallback():
    fallback_called = []

    async def _fallback():
        fallback_called.append(True)

    config = CircuitBreakerConfig(
        name="test_cm",
        failure_threshold=1,
        recovery_timeout=60.0,
        graceful_degradation=True,
        fallback=_fallback,
    )
    cb = CircuitBreaker(config)
    import time

    cb._state = CircuitState.OPEN
    cb._last_failure_time = time.monotonic()

    body_executed = []
    with pytest.raises(CircuitBreakerException) as exc_info:
        async with cb:
            body_executed.append(True)

    assert len(fallback_called) == 0
    assert len(body_executed) == 0
    assert exc_info.value.code == 50301
    assert "service is unavailable (circuit open)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_circuit_breaker_call_substitutes_body_with_fallback():
    async def _fallback():
        return "fallback_result"

    config = CircuitBreakerConfig(
        name="test_call",
        failure_threshold=1,
        recovery_timeout=60.0,
        graceful_degradation=True,
        fallback=_fallback,
    )
    cb = CircuitBreaker(config)
    import time

    cb._state = CircuitState.OPEN
    cb._last_failure_time = time.monotonic()

    target_executed = []

    async def _target():
        target_executed.append(True)
        return "original_result"

    res = await cb.call(_target)
    assert res == "fallback_result"
    assert len(target_executed) == 0


@pytest.mark.asyncio
async def test_circuit_breaker_call_normal_execution():
    config = CircuitBreakerConfig(
        name="test_normal",
        failure_threshold=5,
        recovery_timeout=60.0,
    )
    cb = CircuitBreaker(config)

    async def _target(x: int) -> int:
        return x * 2

    res = await cb.call(_target, 21)
    assert res == 42
