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

import uuid

from app.api.schemas.response import ApiResponse
from app.common.exceptions import AuthException, PipelineRAGFrameException
from app.config import get_settings
from app.db.session import get_db

router: APIRouter = APIRouter()
settings = get_settings()

bearer_scheme = HTTPBearer()

JWT_DENYLIST_PREFIX = "pipeline_rag:jwt_denylist:"


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    username: str
    token: str
    token_type: str = "bearer"
    tokenExpireMinutes: int  # token 过期时间（分钟）


def create_access_token(username: str) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt.expire_minutes)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


async def _get_safe_redis():
    try:
        from app.infra.redis_lease import get_redis

        return get_redis()
    except Exception:
        return None


async def is_token_revoked(jti: str | None) -> bool:
    """检查 Token 是否已在分布式黑名单中"""
    if not jti:
        return False
    try:
        r = await _get_safe_redis()
        if r is None:
            if getattr(settings.jwt, "deny_on_redis_error", False):
                import structlog as _slog

                _slog.get_logger(__name__).error("redis unavailable, fail-closed token revocation check", jti=jti)
                return True
            return False
        exists = await r.exists(f"{JWT_DENYLIST_PREFIX}{jti}")
        return bool(exists)
    except Exception as e:
        import structlog as _slog

        _slog.get_logger(__name__).error("failed to check token revocation in redis", error=str(e), jti=jti)
        if getattr(settings.jwt, "deny_on_redis_error", False):
            return True
        return False


async def revoke_token(token: str) -> None:
    """将 Token 加入 Redis 黑名单，自动设置与 Token 剩余生存期相同的 TTL"""
    try:
        r = await _get_safe_redis()
        if r is None:
            return

        payload = jwt.decode(
            token,
            settings.jwt.secret_key,
            algorithms=[settings.jwt.algorithm],
            options={"verify_exp": False},
        )
        jti = payload.get("jti")
        if not jti:
            import hashlib

            jti = hashlib.md5(token.encode()).hexdigest()

        exp = payload.get("exp")
        now = datetime.now(UTC).timestamp()
        ttl = max(1, int(exp - now)) if exp else settings.jwt.expire_minutes * 60
        await r.setex(f"{JWT_DENYLIST_PREFIX}{jti}", ttl, "1")
    except Exception as e:
        import structlog as _slog

        _slog.get_logger(__name__).warning("failed to revoke token in redis", error=str(e))


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    request: Request = None,  # type: ignore[assignment]  # FastAPI 注入；None 仅为满足测试直调
) -> str:
    """JWT 认证依赖，返回当前用户名（第三轮 #8：通过即记录管理操作审计）"""
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt.secret_key,
            algorithms=[settings.jwt.algorithm],
        )
        username: str = payload.get("sub", "")
        if not username:
            raise AuthException("后台登录无效，请重新登录")

        jti = payload.get("jti")
        if not jti:
            import hashlib

            jti = hashlib.md5(token.encode()).hexdigest()

        if await is_token_revoked(jti):
            raise AuthException("用户已登出，请重新登录")

        _record_audit(username, request)
        return username
    except jwt.ExpiredSignatureError as e:
        raise AuthException("后台登录已过期，请重新登录") from e
    except jwt.InvalidTokenError as e:
        raise AuthException("后台登录无效，请重新登录") from e


def _record_audit(username: str, request) -> None:
    """管理操作审计（第三轮 #8）：操作者/方法/路径/来源 → 结构化日志，可检索与合规追溯"""
    import structlog as _slog

    _slog.get_logger(__name__).info(
        "admin operation audit",
        operator=username,
        event_name="manage_request",
        method=getattr(request, "method", ""),
        path=getattr(request, "url", None) and getattr(request.url, "path", ""),
        client=getattr(request, "client", None) and getattr(request.client, "host", ""),
    )


@router.post(
    "/login",
    summary="管理员登录",
    description="使用用户名和密码登录，返回 JWT Token。Token 有效期由 JWT_EXPIRE_MINUTES 配置控制。",
)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """POST /admin/auth/login"""
    from app.manage.service.admin_auth_service import get_admin_user

    user = await get_admin_user(db, request.username)

    pw_valid = False
    try:
        if user and getattr(user, "password", None):
            pw_valid = bcrypt.checkpw(request.password.encode("utf-8"), user.password.encode("utf-8"))
    except (ValueError, TypeError) as ex:
        import structlog as _slog

        _slog.get_logger(__name__).warning(
            "password hash verification failed due to invalid hash format",
            error=str(ex),
            username=request.username,
        )
        pw_valid = False

    if not user or not pw_valid:
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
    description="注销当前 JWT Token，并加入分布式黑名单，防止多实例或并发重用。",
)
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> dict:
    """POST /admin/auth/logout（加入 Redis 黑名单）"""
    token = None
    if credentials:
        token = credentials.credentials
    elif request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ")

    if token:
        await revoke_token(token)

    return ApiResponse.ok(message="登出成功")


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

            jti = payload.get("jti")
            if not jti:
                import hashlib

                jti = hashlib.md5(token.encode()).hexdigest()

            if await is_token_revoked(jti):
                return JSONResponse(
                    status_code=401, content=ApiResponse.fail("用户已登出，请重新登录", 401)
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
        "/manage/document/cache/purge",
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
        "/manage/evaluation/dataset/experiment",
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
