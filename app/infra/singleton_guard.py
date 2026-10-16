"""多实例运行环境探测（第二轮架构评审·必须优化 1）

历史背景：`ChatRuntimeRegistry`（app/chat/task_info.py）保存 SSE 流式会话的
进程内运行状态。早期版本中「停止会话 / 状态查询」只查本地注册表，
因此必须单 worker / 单副本部署，否则这两项能力会静默失效。

当前状态（已支持多 worker / 多副本，本模块职责收敛为"探测 + 提示"）：

| 能力 | 跨实例机制 |
| :-- | :-- |
| 会话排他执行 | Redis 分布式租约 `pipeline_rag:lock:conversation:{id}` |
| 停止会话 | Redis 取消键 + `pipeline_rag:session:cancel` Pub/Sub 广播 |
| 运行状态查询 | `ChatRuntimeRegistry.is_running_cluster()` = 本地注册表 ∪ 租约键 |
| 实时答案缓冲 | 仍为进程内；跨 worker 时退化为已落库的最新回答 |

本模块在启动时向 Redis 注册当前实例（带 TTL 心跳）并探测是否存在其他活跃实例：
- 探测到多实例 → 记录 info 日志说明各能力的跨实例保障（不阻断启动）
- 探测失败（Redis 不可用）→ 记录 warning

保留本模块的价值：为运维提供"当前是否多实例运行"的可观测信号。
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
            logger.info(
                "pipeline-rag 检测到多实例/多 Worker 运行环境："
                "会话级隔离由 Redis 租约锁保障，跨实例/跨 Worker 会话取消已由 Redis Pub/Sub 广播闭环接管。",
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
