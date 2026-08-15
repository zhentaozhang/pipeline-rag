"""集成测试：Redis 分布式锁并发语义（真实 Redis）"""

import asyncio

import pytest

from app.infra.redis_lease import RedisLeaseManager


async def _acquire_with_conflict(conversation_id: str) -> tuple[bool, bool]:
    """两个实例竞争同一会话锁：第一个成功，第二个失败"""
    mgr1 = RedisLeaseManager(conversation_id)
    mgr2 = RedisLeaseManager(conversation_id)
    first = await mgr1.acquire()
    second = await mgr2.acquire()
    await mgr1.release()
    return first, second


@pytest.mark.integration
async def test_lease_mutual_exclusion(redis_client):
    """并发互斥：同一会话只能被一个实例持有"""
    first, second = await _acquire_with_conflict("conv-integration-1")
    assert first is True
    assert second is False


@pytest.mark.integration
async def test_lease_release_allows_reacquire(redis_client):
    """释放后可被重新获取（锁语义正确）"""
    mgr1 = RedisLeaseManager("conv-integration-2")
    assert await mgr1.acquire() is True
    assert await mgr1.is_owned() is True
    await mgr1.release()
    assert await mgr1.is_owned() is False

    mgr2 = RedisLeaseManager("conv-integration-2")
    assert await mgr2.acquire() is True  # 释放后他人可获取
    await mgr2.release()


@pytest.mark.integration
async def test_lease_owner_mismatch_not_released(redis_client):
    """非持有者释放不影响锁（token 校验）"""
    mgr1 = RedisLeaseManager("conv-integration-3")
    assert await mgr1.acquire() is True
    # 另一个实例尝试释放（owner token 不同）
    mgr2 = RedisLeaseManager("conv-integration-3")
    await mgr2.release()
    assert await mgr1.is_owned() is True  # 锁仍归 mgr1
    await mgr1.release()


@pytest.mark.integration
async def test_concurrent_acquire_only_one_wins(redis_client):
    """并发竞争：N 个并发 acquire 只有 1 个成功"""
    conversation_id = "conv-integration-4"
    results = await asyncio.gather(
        *[RedisLeaseManager(conversation_id).acquire() for _ in range(8)]
    )
    assert sum(1 for r in results if r) == 1
    # 清理：任一成功者释放
    for mgr in [RedisLeaseManager(conversation_id) for _ in range(1)]:
        await mgr.release()
