"""RedisLeaseManager 分布式锁语义测试（mock Redis 客户端，不依赖外部服务）。

覆盖：获取成功、冲突失败、token 不匹配不释放、续期 token 校验。
"""

from types import SimpleNamespace

import pytest

from app.infra.redis_lease import RedisLeaseManager


class _FakeRedis:
    """记录 eval 调用的假 Redis（ACQUIRE/RELEASE/RENEW 均为 Lua eval）"""

    def __init__(self):
        self.evals: list[tuple] = []
        self._locked_by: str | None = None

    async def eval(self, script, numkeys, key, *args):
        self.evals.append((key, args))
        if "psetex" in script:  # ACQUIRE
            if self._locked_by is not None:
                return 0
            self._locked_by = args[0]
            return 1
        if "del" in script:  # RELEASE
            if self._locked_by == args[0]:
                self._locked_by = None
                return 1
            return 0
        if "pexpire" in script:  # RENEW
            return 1 if self._locked_by == args[0] else 0
        return 0

    async def get(self, key):
        return self._locked_by


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr("app.infra.redis_lease.get_redis", lambda: client)
    return client


@pytest.mark.asyncio
async def test_acquire_release_roundtrip(fake_redis, monkeypatch):
    monkeypatch.setattr("app.infra.redis_lease.get_settings", lambda: SimpleNamespace(
        redis=SimpleNamespace(lease_ttl_seconds=30, renew_interval_seconds=10),
        circuit_breaker=SimpleNamespace(default_timeout=30),
    ))
    mgr = RedisLeaseManager("conv-1")
    assert await mgr.acquire() is True
    assert await mgr.is_owned() is True
    await mgr.release()
    assert await mgr.is_owned() is False


@pytest.mark.asyncio
async def test_acquire_conflict_returns_false(fake_redis, monkeypatch):
    monkeypatch.setattr("app.infra.redis_lease.get_settings", lambda: SimpleNamespace(
        redis=SimpleNamespace(lease_ttl_seconds=30, renew_interval_seconds=10),
        circuit_breaker=SimpleNamespace(default_timeout=30),
    ))
    mgr1 = RedisLeaseManager("conv-1")
    mgr2 = RedisLeaseManager("conv-1")
    assert await mgr1.acquire() is True
    assert await mgr2.acquire() is False  # 同一 key 冲突


@pytest.mark.asyncio
async def test_release_owner_mismatch_does_not_clear(fake_redis, monkeypatch):
    monkeypatch.setattr("app.infra.redis_lease.get_settings", lambda: SimpleNamespace(
        redis=SimpleNamespace(lease_ttl_seconds=30, renew_interval_seconds=10),
        circuit_breaker=SimpleNamespace(default_timeout=30),
    ))
    mgr1 = RedisLeaseManager("conv-1")
    assert await mgr1.acquire() is True
    # 另一个实例尝试释放（token 不同）→ 锁不被清除
    mgr2 = RedisLeaseManager("conv-1")
    await mgr2.release()
    assert await mgr1.is_owned() is True


@pytest.mark.asyncio
async def test_is_owned_false_after_renew_give_up(monkeypatch):
    """续期放弃后 is_owned 立即判失（C7：收敛双实例并发窗口）"""
    mgr = RedisLeaseManager("conv-1")
    mgr._lease_give_up = True
    assert await mgr.is_owned() is False


@pytest.mark.asyncio
async def test_renew_loop_sets_give_up_on_owner_mismatch(fake_redis, monkeypatch):
    """续期时锁已被他人抢占（owner mismatch）→ 置 give-up 标志"""
    monkeypatch.setattr("app.infra.redis_lease.get_settings", lambda: SimpleNamespace(
        redis=SimpleNamespace(lease_ttl_seconds=30, renew_interval_seconds=10),
        circuit_breaker=SimpleNamespace(default_timeout=30),
    ))
    mgr = RedisLeaseManager("conv-1")
    assert await mgr.acquire() is True
    # 模拟锁被他人拿走：直接改 fake 的持有者
    fake_redis._locked_by = "someone-else"

    async def _fast_sleep(_):
        pass

    monkeypatch.setattr("asyncio.sleep", _fast_sleep)
    await mgr._renew_loop()
    assert mgr._lease_give_up is True
