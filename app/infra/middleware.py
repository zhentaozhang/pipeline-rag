"""
Request ID 中间件 — 为每个请求注入唯一 ID，便于日志追踪
"""

import uuid

import structlog
from starlette.requests import Request

logger = structlog.get_logger(__name__)


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    # 绑定到 structlog 上下文（当前请求生命周期内有效）
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
