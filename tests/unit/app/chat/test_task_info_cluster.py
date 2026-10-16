"""ChatRuntimeRegistry 的集群级（跨 worker）运行判定测试。

背景：`--workers 4` 部署下 /api/chat 请求可能落到任意 worker，
仅查进程内注册表会把「正在别的 worker 上生成」误判为未运行，
导致会话状态查询与会话列表的 running 标记失真。
"""

from __future__ import annotations

import pytest

from app.chat.task_info import ChatRuntimeRegistry, ChatTaskInfo
from app.infra import redis_lease


@pytest.fixture(autouse=True)
def _clean_registry():
    ChatRuntimeRegistry._registry.clear()
    yield
    ChatRuntimeRegistry._registry.clear()


def _task(cid: str) -> ChatTaskInfo:
    return ChatTaskInfo(conversation_id=cid, question="q")


async def test_local_hit_short_circuits_redis(monkeypatch):
    """本地注册表命中时不应再访问 Redis。"""
    ChatRuntimeRegistry.register(_task("c-local"))

    async def _boom(cid: str) -> bool:  # pragma: no cover - 不应被调用
        raise AssertionError("本地已命中，不应查询 Redis")

    monkeypatch.setattr(redis_lease, "conversation_lease_exists", _boom)

    assert await ChatRuntimeRegistry.is_running_cluster("c-local") is True


async def test_remote_running_detected_via_lease(monkeypatch):
    """本地无任务但集群租约存在 → 判定为运行中。"""

    async def _lease_exists(cid: str) -> bool:
        return cid == "c-remote"

    monkeypatch.setattr(redis_lease, "conversation_lease_exists", _lease_exists)

    assert await ChatRuntimeRegistry.is_running_cluster("c-remote") is True
    assert await ChatRuntimeRegistry.is_running_cluster("c-idle") is False


async def test_running_ids_cluster_unions_local_and_remote(monkeypatch):
    """批量判定取本地注册表与集群租约的并集。"""
    ChatRuntimeRegistry.register(_task("c-local"))

    async def _active() -> set[str]:
        return {"c-remote-1", "c-remote-2"}

    monkeypatch.setattr(redis_lease, "active_conversation_ids", _active)

    ids = await ChatRuntimeRegistry.running_ids_cluster()
    assert ids == {"c-local", "c-remote-1", "c-remote-2"}


async def test_active_count_cluster_takes_max(monkeypatch):
    """集群计数按「本地 ∪ 远端」并集口径，避免多 worker 下被低估。"""
    ChatRuntimeRegistry.register(_task("c-local"))

    async def _active() -> set[str]:
        return {"c-remote-1", "c-remote-2", "c-remote-3"}

    monkeypatch.setattr(redis_lease, "active_conversation_ids", _active)

    # 1 个本地 + 3 个远端 = 4
    assert await ChatRuntimeRegistry.active_count_cluster() == 4
    # 本地口径保持原语义
    assert ChatRuntimeRegistry.active_count() == 1


async def test_active_conversation_ids_degrades_when_redis_unavailable(monkeypatch):
    """Redis 不可用时返回空集合，不抛异常（调用方自行用本地状态兜底）。"""

    def _raise():
        raise RuntimeError("Redis not initialized")

    monkeypatch.setattr(redis_lease, "get_redis", _raise)

    assert await redis_lease.active_conversation_ids() == set()
    assert await redis_lease.conversation_lease_exists("c1") is False
