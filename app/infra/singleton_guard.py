"""单实例部署守卫（第二轮架构评审·必须优化 1）

背景：ChatRuntimeRegistry（app/chat/task_info.py）保存 SSE 流式会话的
进程内运行状态（运行中任务/取消/状态查询）。该状态是"进程级"的——
Redis 租约锁只保证同一会话不被并发处理，不保证"停止/状态查询"请求
落在持有任务的同一实例上。因此**应用必须以单 worker / 单副本方式部署**，
多 worker 或多副本会导致停止会话/状态查询静默失效。

本模块在启动时向 Redis 注册当前实例并检测是否已存在其他活跃实例：
- 发现其他实例 → 记录显式告警日志（不阻断启动，提示部署约束）
- 同会话冲突保护仍由 Redis 租约锁承担（现有机制不变）

若未来需要水平扩展（多副本），前置工作是将会话运行状态迁移到 Redis
（task_info 序列化 + 跨实例取消指令），再移除本守卫。
"""

from __future__ import annotations

import os
import socket
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_INSTANCE_KEY_PREFIX = "pipeline_rag:app:instance"
_HEARTBEAT_TTL_S = 120


def _instance_id() -> str:
    """当前实例唯一标识：hostname + pid"""
    return f"{socket.gethostname()}:{os.getpid()}"


async def register_and_detect_conflicts(redis: Any) -> tuple[str, bool]:
    """注册当前实例并检测多实例冲突。

    返回 (instance_id, has_conflict)：has_conflict=True 表示已存在其他活跃实例。
    注册项带 TTL 心跳，进程退出/崩溃后自动过期（最多残留 120s）。
    """
    instance_id = _instance_id()
    key = f"{_INSTANCE_KEY_PREFIX}:{instance_id}"
    try:
        await redis.set(key, str(time.time()), ex=_HEARTBEAT_TTL_S)
        # 检测其他活跃实例（同前缀、非自身）
        other_keys = []
        async for k in redis.scan_iter(f"{_INSTANCE_KEY_PREFIX}:*"):
            if k != key:
                other_keys.append(k)
        if other_keys:
            logger.warning(
                "pipeline-rag 检测到多个应用实例同时运行："
                "SSE 会话状态为进程内实现（ChatRuntimeRegistry），多 worker / 多副本部署"
                "将导致「停止会话 / 状态查询 / 会话取消」功能失效。"
                "必须保持单 worker / 单副本运行；若需水平扩展，请先将会话状态迁移至 Redis。",
                instance=instance_id,
                other_instances=[str(k) for k in other_keys],
            )
            return instance_id, True
        return instance_id, False
    except Exception:
        logger.warning(
            "singleton guard 检测失败（Redis 不可用），无法校验单实例约束",
            exc_info=True,
        )
        return instance_id, False
