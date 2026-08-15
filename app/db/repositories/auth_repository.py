from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import AdminUser


class AuthRepository:
    @staticmethod
    async def get_admin_user(db: AsyncSession, username: str) -> AdminUser | None:
        """按用户名查询管理员（修复：原实现误用不存在的 AdminUser.account 字段，登录必崩）"""
        row = await db.execute(select(AdminUser).where(AdminUser.username == username))
        return row.scalar_one_or_none()
