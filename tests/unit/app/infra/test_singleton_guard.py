"""单实例守卫（第二轮架构评审·必须优化 1）：注册 + 多实例冲突检测"""

import pytest

from app.infra.singleton_guard import register_and_detect_conflicts


class _FakeRedis:
    """极简 Redis 双方法 fake（set + scan_iter）"""

    def __init__(self, existing: list[str] | None = None):
        self._store = dict(existing or {})

    async def set(self, key, value, ex=None):
        self._store[key] = value
        return True

    async def scan_iter(self, pattern):
        import fnmatch

        for k in self._store:
            if fnmatch.fnmatch(k, pattern):
                yield k


@pytest.mark.asyncio
async def test_single_instance_no_conflict():
    redis = _FakeRedis()
    instance_id, conflict = await register_and_detect_conflicts(redis)
    assert conflict is False
    assert f"pipeline_rag:app:instance:{instance_id}" in redis._store


@pytest.mark.asyncio
async def test_conflict_detected_with_other_instance():
    redis = _FakeRedis(existing={"pipeline_rag:app:instance:other-host:999": "1700000000"})
    _, conflict = await register_and_detect_conflicts(redis)
    assert conflict is True


@pytest.mark.asyncio
async def test_self_key_not_counted_as_conflict():
    """同一实例重复注册（如重启）不应误报：旧 key 未过期时可能短暂同 pid"""
    redis = _FakeRedis()
    first_id, conflict1 = await register_and_detect_conflicts(redis)
    assert conflict1 is False
    # 模拟同实例重新注册（覆盖自身 key）
    instance_id, conflict2 = await register_and_detect_conflicts(redis)
    assert conflict2 is False
    assert instance_id == first_id


@pytest.mark.asyncio
async def test_redis_failure_degrades_gracefully():
    """Redis 不可用时降级为无冲突（不阻断启动）"""

    class _BrokenRedis(_FakeRedis):
        async def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

    _, conflict = await register_and_detect_conflicts(_BrokenRedis())
    assert conflict is False
