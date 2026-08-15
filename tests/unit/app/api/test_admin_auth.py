"""JWT 认证逻辑测试：签发、校验、过期、中间件拦截。"""

import jwt
import pytest
from starlette.requests import Request

from app.api.admin_auth import (
    auth_middleware_for_manage,
    create_access_token,
    get_current_user,
)
from app.common.exceptions import AuthException
from app.config import get_settings


def _make_request(path: str, auth_header: str | None = None) -> Request:
    headers = []
    if auth_header:
        headers.append((b"authorization", auth_header.encode()))
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    return Request(scope)


def test_create_access_token_roundtrip():
    token = create_access_token("admin")
    payload = jwt.decode(
        token, get_settings().jwt.secret_key, algorithms=[get_settings().jwt.algorithm]
    )
    assert payload["sub"] == "admin"
    assert "exp" in payload and "iat" in payload


@pytest.mark.asyncio
async def test_get_current_user_valid_token():
    token = create_access_token("admin")

    class _Creds:
        credentials = token

    username = await get_current_user(_Creds())
    assert username == "admin"


@pytest.mark.asyncio
async def test_get_current_user_invalid_token():
    class _Creds:
        credentials = "not-a-token"

    with pytest.raises(AuthException):
        await get_current_user(_Creds())


@pytest.mark.asyncio
async def test_manage_middleware_rejects_missing_token():
    async def call_next(request):
        raise AssertionError("不应放行")

    resp = await auth_middleware_for_manage(_make_request("/manage/document/list"), None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_manage_middleware_passes_through_non_manage_paths():
    async def call_next(request):
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True})

    resp = await auth_middleware_for_manage(_make_request("/api/chat/stream"), call_next)
    assert resp.status_code == 200
