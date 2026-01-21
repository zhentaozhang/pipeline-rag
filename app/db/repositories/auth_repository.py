from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import AdminUser


class AuthRepository:
    @staticmethod
    async def get_admin_user(db: AsyncSession, account: str) -> AdminUser | None:
        return await db.scalar(select(AdminUser).where(AdminUser.account == account))
