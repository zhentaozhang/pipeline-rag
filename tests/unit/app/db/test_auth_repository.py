"""AuthRepository 回归测试：登录查询必须使用 AdminUser.username 字段。

历史 Bug：实现误用不存在的 AdminUser.account 字段，登录链路运行时必崩
（AttributeError），因该模块零测试覆盖而未被发现。
"""

from types import SimpleNamespace

import pytest

from app.db.repositories.auth_repository import AuthRepository


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


@pytest.mark.asyncio
async def test_get_admin_user_queries_by_username():
    """查询条件必须落在 username 列（防 account 字段回归）"""
    admin = SimpleNamespace(username="admin")
    captured: dict = {}

    async def fake_execute(stmt):
        captured["stmt"] = stmt
        return _FakeResult(admin)

    db = SimpleNamespace(execute=fake_execute)
    result = await AuthRepository.get_admin_user(db, "admin")
    assert result is admin
    # 编译后 SQL 必须引用 admin_user.username 而非不存在的 account 列
    sql = str(captured["stmt"])
    assert "admin_user.username" in sql
    assert "account" not in sql


@pytest.mark.asyncio
async def test_get_admin_user_returns_none_when_missing():
    async def fake_execute(stmt):
        return _FakeResult(None)

    db = SimpleNamespace(execute=fake_execute)
    assert await AuthRepository.get_admin_user(db, "nobody") is None
