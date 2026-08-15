"""
Redis 滑动窗口限流器 + FastAPI ASGI 中间件

基于 Lua 脚本的原子滑动窗口：
1. ZREMRANGEBYSCORE 清除窗口外记录
2. ZCARD 计数
3. >= limit 拒绝，否则 ZADD + PEXPIRE

多维客户端识别：JWT user → API Key hash → IP
"""

import time
from collections.abc import Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response

from app.common.exceptions import RateLimitException
from app.config import get_settings
from app.infra.metrics import RATE_LIMIT_HITS_TOTAL
from app.infra.redis_lease import _redis as _redis_client

logger = structlog.get_logger(__name__)

RATE_LIMIT_KEY_PREFIX = "pipeline_rag:ratelimit"

_SLIDING_WINDOW_SCRIPT = """
redis.replicate_commands()
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
    return {0, 0}
end
redis.call('ZADD', key, now, now)
redis.call('PEXPIRE', key, window * 1000 + 1000)
return {1, limit - count - 1}
"""


def _client_identity(request: Request) -> str:
    """多维度客户端识别：JWT → API Key → IP"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt

            settings = get_settings()
            payload = jwt.decode(
                auth.removeprefix("Bearer "),
                settings.jwt.secret_key,
                algorithms=[settings.jwt.algorithm],
            )
            username = payload.get("sub", "")
            if username:
                return f"user:{username}"
        except Exception:
            pass

    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        import hashlib

        return f"apikey:{hashlib.md5(api_key.encode()).hexdigest()}"

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and get_settings().rate_limit.trust_proxy_count > 0:
        # 仅信任配置层数的反代：从右侧数第 trust_proxy_count+1 个地址为真实客户端
        ips = [p.strip() for p in forwarded.split(",")]
        idx = len(ips) - get_settings().rate_limit.trust_proxy_count - 1
        if idx >= 0 and ips[idx]:
            return ips[idx]
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


async def check_rate_limit(key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    """Redis 滑动窗口限流检查。返回 (allowed, remaining, window_end)"""
    if _redis_client is None:
        return True, limit, int(time.time() + window_seconds)
    now = time.time()
    result = await _redis_client.eval(_SLIDING_WINDOW_SCRIPT, 1, key, now, window_seconds, limit)
    allowed = bool(result[0])
    remaining = int(result[1])
    window_end = int(now + window_seconds)
    return allowed, remaining, window_end


def _route_group(path: str) -> str | None:
    if path.startswith("/api/chat/"):
        return "chat"
    if path.startswith("/admin/auth/"):
        return "auth"
    if path.startswith("/manage/"):
        return "manage"
    return None


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Response]
) -> Response:
    settings = get_settings()
    if not settings.rate_limit.enabled:
        return await call_next(request)

    group = _route_group(request.url.path)
    if group is None:
        return await call_next(request)

    limit = getattr(settings.rate_limit, f"{group}_calls", None)
    window = getattr(settings.rate_limit, f"{group}_window_seconds", None)
    if limit is None or window is None:
        return await call_next(request)

    identity = _client_identity(request)
    key = f"{RATE_LIMIT_KEY_PREFIX}:{group}:{identity}"

    allowed, remaining, reset_at = await check_rate_limit(key, limit, window)
    if not allowed:
        RATE_LIMIT_HITS_TOTAL.labels(group=group).inc()
        logger.warning("rate_limit_exceeded", group=group, identity=identity, limit=limit)
        raise RateLimitException(
            f"请求过于频繁，{group} 接口每分钟最多 {limit} 次",
            retry_after=reset_at - int(time.time()),
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_at)
    return response
