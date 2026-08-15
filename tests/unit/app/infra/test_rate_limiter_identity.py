"""
限流客户端身份识别（X-Forwarded-For 信任策略）测试。

trust_proxy_count = 0（默认）：不信任 XFF，用直连 IP，防伪造绕过。
trust_proxy_count = N：从 XFF 右侧数第 N+1 个地址作为客户端。
"""

import pytest
from starlette.requests import Request

from app.config import get_settings
from app.infra.rate_limiter import _client_identity


def _make_request(xff: str | None, client_host: str = "9.9.9.9") -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat/stream",
        "headers": headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


@pytest.mark.parametrize(
    "trust_proxy_count,xff,expected",
    [
        # 默认不信任 XFF：伪造头被忽略，取直连 IP
        (0, "1.2.3.4", "9.9.9.9"),
        (0, "1.2.3.4, 5.6.7.8", "9.9.9.9"),
        # 信任 1 层代理：取 XFF 右侧第 2 个（真实客户端）
        (1, "1.2.3.4, 5.6.7.8", "1.2.3.4"),
        # 信任 2 层代理：client, proxy1, proxy2 → 取最左
        (2, "1.2.3.4, 5.6.7.8, 8.8.8.8", "1.2.3.4"),
        # 无 XFF 头：回退直连 IP
        (1, None, "9.9.9.9"),
        # 代理链短于信任层数（异常）：回退最左地址
        (3, "1.2.3.4, 5.6.7.8", "1.2.3.4"),
    ],
)
def test_client_identity_trust_proxy(monkeypatch, trust_proxy_count, xff, expected):
    settings = get_settings()
    monkeypatch.setattr(settings.rate_limit, "trust_proxy_count", trust_proxy_count)
    req = _make_request(xff)
    assert _client_identity(req) == expected


def test_client_identity_uses_bearer_jwt_first(monkeypatch):
    """已认证用户优先按 JWT 身份限流，不依赖 IP"""
    settings = get_settings()
    monkeypatch.setattr(settings.rate_limit, "trust_proxy_count", 0)
    import jwt

    token = jwt.encode(
        {"sub": "tester"},
        settings.jwt.secret_key,
        algorithm=settings.jwt.algorithm,
    )
    headers = [(b"authorization", f"Bearer {token}".encode())]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat/stream",
        "headers": headers,
        "client": ("9.9.9.9", 12345),
    }
    assert _client_identity(Request(scope)) == "user:tester"
