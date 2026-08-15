"""
Redis 分布式锁（RedisLeaseManager）

功能：
- acquire()：以 conversationId 为 key 抢占锁，防止同一会话被多个实例重复处理
- renew()：长对话自动续期，防止超时后被其他实例抢占
- release()：无论成功失败，统一触发清理
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
import structlog

from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry

logger = structlog.get_logger(__name__)
settings = get_settings()

_redis: aioredis.Redis | None = None

_redis_breaker = CircuitBreakerRegistry.get_or_register(
    "redis",
    CircuitBreakerConfig(
        name="redis",
        failure_threshold=3,
        recovery_timeout=15.0,
        timeout=settings.circuit_breaker.default_timeout,
    ),
)

LOCK_KEY_PREFIX = "pipeline_rag:lock:conversation:"

# Lua 脚本保证安全释放和续期
ACQUIRE_SCRIPT = """
if redis.call('exists', KEYS[1]) == 0 then
    redis.call('psetex', KEYS[1], ARGV[2], ARGV[1]);
    return 1;
end;
return 0;
"""

RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
else
    return 0
end
"""


async def init_redis() -> None:
    """在 lifespan 启动时调用"""
    global _redis
    _redis = aioredis.from_url(
        settings.redis.url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.redis.max_connections,
    )
    await _redis.ping()  # type: ignore[misc]


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis


class RedisLeaseManager:
    """
    基于 SET NX EX 的分布式锁，支持自动续期。
    用法：
        async with RedisLeaseManager.lease(conversation_id) as acquired:
            if not acquired:
                raise ConflictError("会话正在处理中")
            ...业务逻辑...
    """

    def __init__(self, conversation_id: str, ttl: int | None = None) -> None:
        self.key = f"{LOCK_KEY_PREFIX}{conversation_id}"
        self.ttl = ttl if ttl is not None else settings.redis.lease_ttl_seconds
        self.owner_id = str(uuid.uuid4())
        self._renew_task: asyncio.Task | None = None
        self._consecutive_failures: int = 0
        self._first_failure_time: float = 0.0
        # 体检 C7：续期放弃（锁已过期/他人抢占）后立即判失，收敛双实例并发窗口
        self._lease_give_up: bool = False

    @property
    def lock_name(self) -> str:
        return self.key

    @property
    def lock_token(self) -> str:
        return self.owner_id

    async def acquire(self) -> bool:
        """尝试获取锁，成功返回 True（使用 Lua 脚本保证原子性）"""
        if self.ttl <= 0:
            logger.error("lease acquire with invalid TTL", key=self.key, ttl=self.ttl)
            return False
        r = get_redis()
        ttl_ms = self.ttl * 1000
        async with _redis_breaker:
            result = await r.eval(ACQUIRE_SCRIPT, 1, self.key, self.owner_id, ttl_ms)
        acquired = result == 1
        if acquired:
            self._start_renewer()
            logger.debug("lease acquired", key=self.key)
        else:
            logger.warning("lease conflict", key=self.key)
        return bool(acquired)

    FAILURE_THRESHOLD: int = 10
    FAILURE_WINDOW_SECONDS: int = 60

    async def is_owned(self) -> bool:
        """检查锁是否仍由当前实例持有。

        优先检查本地 give-up 标志（续期已放弃 → 立即判失）；
        否则采用连续失败计数 + 时间窗口，仅在 60 秒内连续失败 10 次后认定锁丢失。
        避免瞬时的 Redis 网络抖动或断路器短暂开启导致对话中断。
        """
        if self._lease_give_up:
            logger.warning("lease ownership given up (renew abandoned)", key=self.key)
            return False
        try:
            r = get_redis()
            async with _redis_breaker:
                current_owner = await r.get(self.key)
            self._consecutive_failures = 0
            self._first_failure_time = 0.0
            return current_owner == self.owner_id
        except Exception:
            now = time.monotonic()
            if self._first_failure_time == 0.0:
                self._first_failure_time = now
            elif now - self._first_failure_time > self.FAILURE_WINDOW_SECONDS:
                self._consecutive_failures = 1
                self._first_failure_time = now
            else:
                self._consecutive_failures += 1

            logger.warning(
                "lease ownership check failed",
                key=self.key,
                consecutive_failures=self._consecutive_failures,
                first_failure_elapsed=round(now - self._first_failure_time, 1),
                exc_info=True,
            )
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                logger.error(
                    "lease ownership check failed consecutively, assuming lost",
                    key=self.key,
                    consecutive_failures=self._consecutive_failures,
                )
                return False
            return True

    async def release(self) -> None:
        """释放锁，同时取消续期任务"""
        if self._renew_task:
            self._renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renew_task
        r = get_redis()
        async with _redis_breaker:
            res = await r.eval(RELEASE_SCRIPT, 1, self.key, self.owner_id)
        if res:
            logger.debug("lease released", key=self.key)
        else:
            logger.warning("lease release failed (owner mismatch)", key=self.key)

    def _start_renewer(self) -> None:
        self._renew_task = asyncio.create_task(self._renew_loop())

    _MAX_RENEW_RETRIES: int = 5

    async def _renew_loop(self) -> None:
        """后台续期：按配置间隔刷新 TTL"""
        renew_failures = 0
        while True:
            try:
                await asyncio.sleep(settings.redis.renew_interval_seconds)
                r = get_redis()
                async with _redis_breaker:
                    res = await r.eval(RENEW_SCRIPT, 1, self.key, self.owner_id, self.ttl * 1000)
                if res:
                    renew_failures = 0
                    logger.debug("lease renewed", key=self.key)
                else:
                    logger.warning("lease renew failed (owner mismatch)", key=self.key)
                    self._lease_give_up = True
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                renew_failures += 1
                logger.warning(
                    "lease renew error",
                    key=self.key,
                    renew_failures=renew_failures,
                    max_retries=self._MAX_RENEW_RETRIES,
                    exc_info=True,
                )
                if renew_failures >= self._MAX_RENEW_RETRIES:
                    logger.error(
                        "lease renew failed consecutively, giving up",
                        key=self.key,
                        renew_failures=renew_failures,
                    )
                    self._lease_give_up = True
                    break

    @classmethod
    @contextlib.asynccontextmanager
    async def lease(cls, conversation_id: str, ttl: int | None = None) -> AsyncIterator[bool]:
        """异步上下文管理器，自动 acquire + release"""
        mgr = cls(conversation_id, ttl)
        acquired = await mgr.acquire()
        try:
            yield acquired
        finally:
            if acquired:
                await mgr.release()
