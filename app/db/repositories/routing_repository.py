from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.routing import KnowledgeRouteTrace


class RoutingRepository:
    @staticmethod
    async def query_traces(
        db: AsyncSession,
        page: int,
        size: int,
        conversation_id: str | None = None,
        mode: str | None = None,
        route_status: str | None = None,
    ) -> tuple[list, int]:
        query = select(KnowledgeRouteTrace)
        if conversation_id:
            query = query.where(KnowledgeRouteTrace.conversation_id == conversation_id)
        if mode:
            query = query.where(KnowledgeRouteTrace.mode == mode)
        if route_status:
            query = query.where(KnowledgeRouteTrace.route_status == route_status)

        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        stmt = (
            query.order_by(desc(KnowledgeRouteTrace.created_at))
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return list(rows), total or 0
