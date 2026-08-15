"""
事件总线默认监听者：把关键对话事件转为 Prometheus 指标与结构化日志。

背景（体检 B3）：此前事件总线「只发不收」（listeners/ 为空目录），
conversation.started / state.transition / memory.saved 等事件被 emit 后无任何消费，
纯属无效开销。本监听者让事件流产生可观测价值：

- conversation.completed → 新增耗时直方图 + 结构化日志
- conversation.failed / conversation.cancelled → 结束状态计数器 + 日志
- memory.saved → 日志（记忆压缩链路可观测）

不重复既有计数：EXCHANGE_TOTAL / ACTIVE_EXCHANGES 由 service_executor 维护，
此处只补充新增维度。
"""

import structlog
from prometheus_client import Counter, Histogram

from app.eventbus.bus import bus
from app.eventbus.events import (
    ConversationCancelledPayload,
    ConversationCompletedPayload,
    ConversationFailedPayload,
    Event,
    MemorySavedPayload,
)

logger = structlog.get_logger(__name__)

EXCHANGE_DURATION_SECONDS = Histogram(
    "exchange_duration_seconds",
    "对话轮次总耗时（秒）",
    buckets=(1, 3, 5, 10, 30, 60, 120, 300, 600),
)
EXCHANGE_END_TOTAL = Counter("exchange_end_total", "对话轮次结束分布", ["status"])


async def _on_conversation_completed(event: Event[ConversationCompletedPayload]) -> None:
    payload = event.payload
    EXCHANGE_DURATION_SECONDS.observe(payload.total_duration_ms / 1000.0)
    logger.info(
        "event.conversation.completed",
        exchange_id=payload.exchange_id,
        turn_status=payload.turn_status,
        total_tokens=payload.total_tokens,
        total_duration_ms=payload.total_duration_ms,
    )


async def _on_conversation_failed(event: Event[ConversationFailedPayload]) -> None:
    payload = event.payload
    EXCHANGE_END_TOTAL.labels(status="failed").inc()
    logger.error(
        "event.conversation.failed",
        exchange_id=payload.exchange_id,
        error=payload.error,
    )


async def _on_conversation_cancelled(event: Event[ConversationCancelledPayload]) -> None:
    payload = event.payload
    EXCHANGE_END_TOTAL.labels(status="cancelled").inc()
    logger.warning("event.conversation.cancelled", exchange_id=payload.exchange_id)


async def _on_memory_saved(event: Event[MemorySavedPayload]) -> None:
    payload = event.payload
    logger.info(
        "event.memory.saved",
        conversation_id=payload.conversation_id,
        exchange_id=payload.exchange_id,
    )


def register_listeners() -> None:
    """注册默认监听者（幂等：重复注册由 bus.unregister 场景自行管理，业务层仅调用一次）"""
    bus.register("conversation.completed", _on_conversation_completed)
    bus.register("conversation.failed", _on_conversation_failed)
    bus.register("conversation.cancelled", _on_conversation_cancelled)
    bus.register("memory.saved", _on_memory_saved)
    logger.info("eventbus listeners registered", count=4)
