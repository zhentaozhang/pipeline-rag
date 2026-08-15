"""管理员认证 API — /admin/auth/*  +  /manage/** 全局中间件"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.response import ApiResponse
from app.common.exceptions import AuthException, PipelineRAGFrameException
from app.config import get_settings
from app.db.session import get_db

router: APIRouter = APIRouter()
settings = get_settings()

bearer_scheme = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    username: str
    token: str
    token_type: str = "bearer"
    tokenExpireMinutes: int  # token 过期时间（分钟）


def create_access_token(username: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt.expire_minutes)
    payload = {"sub": username, "exp": expire, "iat": datetime.now(UTC)}
    return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """JWT 认证依赖，返回当前用户名"""

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt.secret_key,
            algorithms=[settings.jwt.algorithm],
        )
        username: str = payload.get("sub", "")
        if not username:
            raise AuthException("后台登录无效，请重新登录")
        return username
    except jwt.ExpiredSignatureError as e:
        raise AuthException("后台登录已过期，请重新登录") from e
    except jwt.InvalidTokenError as e:
        raise AuthException("后台登录无效，请重新登录") from e


@router.post(
    "/login",
    summary="管理员登录",
    description="使用用户名和密码登录，返回 JWT Token。Token 有效期由 JWT_EXPIRE_MINUTES 配置控制。",
)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """POST /admin/auth/login"""
    from app.manage.service.admin_auth_service import get_admin_user

    user = await get_admin_user(db, request.username)

    if not user or not bcrypt.checkpw(request.password.encode(), user.password.encode()):
        # 返回 HTTP 200 + ApiResponse body
        raise PipelineRAGFrameException(401, "账号或密码不正确")

    if not getattr(user, "is_active", True):
        raise PipelineRAGFrameException(403, "账户已被禁用")

    token = create_access_token(user.username)
    return ApiResponse.ok(
        data=TokenResponse(
            username=user.username,
            token=token,
            tokenExpireMinutes=settings.jwt.expire_minutes,
        ).model_dump()
    )


@router.post(
    "/logout",
    summary="管理员登出",
    description="JWT 无状态登出，客户端丢弃 Token 即可。此端点用于兼容前端流程。",
)
async def logout() -> dict:
    """POST /admin/auth/logout（JWT 无状态，客户端丢弃 token 即可）"""
    return ApiResponse.ok()


@router.get(
    "/me",
    summary="当前用户信息",
    description="获取当前已登录管理员用户信息。需在请求头中携带有效的 Bearer Token。",
)
async def get_me(current_user: str = Depends(get_current_user)) -> dict:
    """GET /admin/auth/me — 获取当前用户信息"""
    return ApiResponse.ok(data={"username": current_user})


# ── 全局中间件（自动拦截 /manage/**）────────────────────────────────────────

MANAGE_PREFIX = "/manage/"


async def auth_middleware_for_manage(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """FastAPI 中间件：自动拦截 /manage/** 请求，无需每个路由重复声明 Depends"""
    if request.url.path.startswith(MANAGE_PREFIX) and request.method not in ("OPTIONS", "HEAD"):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content=ApiResponse.fail("缺失或无效的 Authorization header", 401)
            )
        token = auth_header.removeprefix("Bearer ")
        try:
            payload = jwt.decode(
                token, settings.jwt.secret_key, algorithms=[settings.jwt.algorithm]
            )
            username = payload.get("sub", "")
            if not username:
                return JSONResponse(
                    status_code=401, content=ApiResponse.fail("后台登录无效，请重新登录", 401)
                )
            request.state.current_user = username
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=401, content=ApiResponse.fail("后台登录已过期，请重新登录", 401)
            )
        except jwt.InvalidTokenError:
            return JSONResponse(
                status_code=401, content=ApiResponse.fail("后台登录无效，请重新登录", 401)
            )
    response = await call_next(request)
    return response


# ── 聊天 API 认证中间件 ──────────────────────────────────────────────────────

CHAT_PREFIX = "/api/chat"


async def chat_auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """FastAPI 中间件：APP_API_KEY 非空时拦截 /api/chat/** 请求"""
    api_key = getattr(settings.app, "api_key", "")
    if not api_key:
        return await call_next(request)

    if request.url.path.startswith(CHAT_PREFIX) and request.method not in ("OPTIONS", "HEAD"):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header.removeprefix("Bearer ") != api_key:
            return JSONResponse(
                status_code=401,
                content=ApiResponse.fail("缺失或无效的 API Key", 401),
            )
    return await call_next(request)


# ── 预览模式中间件 ──────────────────────────────────────────────────────────

PREVIEW_BLOCKED_PATHS = frozenset(
    {
        "/api/chat/stream",
        "/api/chat/session/stop",
        "/api/chat/session/reset",
        "/api/chat/session/summary/rebuild",
        "/manage/document/upload",
        "/manage/document/delete",
        "/manage/document/retry",
        "/manage/document/strategy/confirm",
        "/manage/document/index/build",
        "/manage/graph/blacklist",
        "/manage/knowledge/scope/save",
        "/manage/knowledge/scope/delete",
        "/manage/knowledge/scope/topic/bind",
        "/manage/knowledge/topic/save",
        "/manage/knowledge/topic/delete",
        "/manage/knowledge/document/profile/regenerate",
        "/manage/knowledge/document/profile/batch/regenerate",
        "/manage/knowledge/topic/document/save",
        "/manage/knowledge/topic/document/remove",
        "/manage/evaluation/dataset/run",
        "/manage/evaluation/dataset/delete",
    }
)


async def preview_mode_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """FastAPI 中间件：线上只读展示模式，拦截写操作"""
    preview_settings = getattr(settings, "preview", None)
    if not preview_settings or not preview_settings.enabled:
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    from urllib.parse import unquote

    path = unquote(request.url.path)
    # 规范化路径：移除重复斜杠和相对路径段，防止 /manage//upload 或 /manage/./upload 绕过
    normalized = "/" + "/".join(seg for seg in path.split("/") if seg not in ("", "."))
    if normalized not in PREVIEW_BLOCKED_PATHS:
        return await call_next(request)

    message = preview_settings.message
    if path == "/api/chat/stream":
        import json

        from fastapi.responses import Response

        sse_error = f"data: {json.dumps({'error': message})}\n\n"
        return Response(
            content=sse_error,
            status_code=200,
            media_type="text/event-stream;charset=UTF-8",
        )
    return JSONResponse(
        status_code=200,
        content=ApiResponse.fail(message),
    )
