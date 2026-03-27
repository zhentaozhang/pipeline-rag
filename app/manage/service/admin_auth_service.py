from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.auth_repository import AuthRepository

if TYPE_CHECKING:
    from app.db.models.auth import AdminUser

logger = structlog.get_logger(__name__)


async def get_admin_user(db: AsyncSession, username: str) -> AdminUser | None:
    return await AuthRepository.get_admin_user(db, username)
