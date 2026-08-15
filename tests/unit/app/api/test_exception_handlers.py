"""全局异常处理器的状态码映射测试。

约定（体检 C2 记录）：业务异常默认返回 HTTP 200 + body.code；
Auth → 401、RateLimit → 429（带 Retry-After）、参数错误 → 400、校验 → 422、未知 → 500。
"""

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError

from app.api.exception_handlers import (
    global_exception_handler,
    pipeline_rag_exception_handler,
    validation_exception_handler,
)
from app.common.exceptions import (
    ArgumentException,
    AuthException,
    PipelineRAGFrameException,
    RateLimitException,
)


def _fake_request() -> Request:
    scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
    return Request(scope)


@pytest.mark.asyncio
async def test_auth_exception_returns_401():
    resp = await pipeline_rag_exception_handler(_fake_request(), AuthException("未登录"))
    assert resp.status_code == 401
    assert resp.body  # JSON body 含 code/message


@pytest.mark.asyncio
async def test_rate_limit_exception_returns_429_with_retry_after():
    exc = RateLimitException("请求过于频繁", retry_after=42)
    resp = await pipeline_rag_exception_handler(_fake_request(), exc)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "42"


@pytest.mark.asyncio
async def test_argument_exception_returns_400():
    resp = await pipeline_rag_exception_handler(_fake_request(), ArgumentException("参数错误"))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_generic_business_exception_returns_400_with_code():
    """约定（体检 C2 决策）：普通业务异常返回 HTTP 400 + body code（不再 200）"""
    resp = await pipeline_rag_exception_handler(
        _fake_request(), PipelineRAGFrameException(401, "账号或密码不正确")
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_validation_exception_returns_422():
    exc = RequestValidationError(errors=[{"loc": ("body", "question"), "msg": "field required"}])
    resp = await validation_exception_handler(_fake_request(), exc)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_exception_returns_500():
    resp = await global_exception_handler(_fake_request(), RuntimeError("boom"))
    assert resp.status_code == 500
