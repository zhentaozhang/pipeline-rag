"""
MetricsService — 运维看板指标聚合

从已有的 DB 表和进程内注册表聚合：
- 概览：Token 用量、成本、活跃会话、失败率、平均响应时间
- 性能基准：各阶段 P50/P90/P99 耗时
- Token 趋势：最近 N 天每日消耗
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class MetricsOverview:
    def __init__(
        self,
        total_exchanges: int = 0,
        failed_exchanges: int = 0,
        avg_response_time_ms: float = 0.0,
        active_conversations: int = 0,
        today_tokens: int = 0,
        today_cost: float = 0.0,
        total_tokens: int = 0,
        total_cost: float = 0.0,
    ):
        self.total_exchanges = total_exchanges
        self.failed_exchanges = failed_exchanges
        self.avg_response_time_ms = avg_response_time_ms
        self.active_conversations = active_conversations
        self.today_tokens = today_tokens
        self.today_cost = today_cost
        self.total_tokens = total_tokens
        self.total_cost = total_cost

    @property
    def error_rate(self) -> float:
        if self.total_exchanges == 0:
            return 0.0
        return round(self.failed_exchanges / self.total_exchanges * 100, 2)

    def to_dict(self) -> dict:
        return {
            "totalExchanges": self.total_exchanges,
            "failedExchanges": self.failed_exchanges,
            "errorRate": self.error_rate,
            "avgResponseTimeMs": round(self.avg_response_time_ms, 1),
            "activeConversations": self.active_conversations,
            "todayTokens": self.today_tokens,
            "todayCost": round(self.today_cost, 6),
            "totalTokens": self.total_tokens,
            "totalCost": round(self.total_cost, 6),
        }


class MetricsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self) -> MetricsOverview:
        from app.db.models.conversation import ConversationExchange
        from app.db.models.rag_observability import ChatModelUsageTrace

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        exchange_count_stmt = select(sa_func.count(ConversationExchange.id))
        total_exchanges_result = await self.db.execute(exchange_count_stmt)
        total_exchanges = total_exchanges_result.scalar() or 0

        failed_count_stmt = select(sa_func.count(ConversationExchange.id)).where(
            ConversationExchange.turn_status == 3
        )
        failed_result = await self.db.execute(failed_count_stmt)
        failed_exchanges = failed_result.scalar() or 0

        avg_response_stmt = select(
            sa_func.avg(ConversationExchange.total_response_time_ms)
        ).where(ConversationExchange.total_response_time_ms.isnot(None))
        avg_result = await self.db.execute(avg_response_stmt)
        avg_response_time_ms = float(avg_result.scalar() or 0.0)

        from app.chat.task_info import ChatRuntimeRegistry

        active_conversations = ChatRuntimeRegistry.active_count()

        today_usage_stmt = (
            select(
                sa_func.coalesce(sa_func.sum(ChatModelUsageTrace.total_tokens), 0),
                sa_func.coalesce(sa_func.sum(ChatModelUsageTrace.cost_usd), 0.0),
            ).where(
                ChatModelUsageTrace.created_at >= today_start,
                ChatModelUsageTrace.created_at < today_end,
            )
        )
        today_result = await self.db.execute(today_usage_stmt)
        today_row = today_result.one()
        today_tokens = int(today_row[0] or 0)
        today_cost = float(today_row[1] or 0.0)

        total_usage_stmt = select(
            sa_func.coalesce(sa_func.sum(ChatModelUsageTrace.total_tokens), 0),
            sa_func.coalesce(sa_func.sum(ChatModelUsageTrace.cost_usd), 0.0),
        )
        total_result = await self.db.execute(total_usage_stmt)
        total_row = total_result.one()
        total_tokens = int(total_row[0] or 0)
        total_cost = float(total_row[1] or 0.0)

        return MetricsOverview(
            total_exchanges=total_exchanges,
            failed_exchanges=failed_exchanges,
            avg_response_time_ms=avg_response_time_ms,
            active_conversations=active_conversations,
            today_tokens=today_tokens,
            today_cost=today_cost,
            total_tokens=total_tokens,
            total_cost=total_cost,
        )

    async def get_usage_trend(self, days: int = 14) -> list[dict]:
        from app.db.models.rag_observability import ChatModelUsageTrace

        since = datetime.now(UTC) - timedelta(days=days)

        trend_stmt = (
            select(
                sa_func.date(ChatModelUsageTrace.created_at).label("day"),
                sa_func.coalesce(sa_func.sum(ChatModelUsageTrace.total_tokens), 0).label("tokens"),
                sa_func.coalesce(sa_func.sum(ChatModelUsageTrace.cost_usd), 0.0).label("cost"),
                sa_func.count(ChatModelUsageTrace.id).label("calls"),
            )
            .where(ChatModelUsageTrace.created_at >= since)
            .group_by(text("day"))
            .order_by(text("day"))
        )
        result = await self.db.execute(trend_stmt)
        rows = result.all()

        return [
            {
                "date": str(row.day),
                "tokens": int(row.tokens),
                "cost": round(float(row.cost), 6),
                "calls": int(row.calls),
            }
            for row in rows
        ]


