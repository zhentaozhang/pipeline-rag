"""P3-3 扩展：网页爬虫连接器——URL 规范化/去重/同域过滤/禁用短路"""

import pytest

from app.document.connectors.web_connector import (
    _extract_links,
    _is_same_domain,
    _slugify,
    normalize_url,
)


def test_normalize_url_strips_tracking_and_fragment():
    raw = "https://Docs.Example.com/path/page?utm_source=news&id=42#section"
    norm = normalize_url(raw)
    assert norm == "https://docs.example.com/path/page?id=42"
    # 无 query 时不应带多余 ?
    assert normalize_url("https://example.com/a") == "https://example.com/a"


def test_normalize_url_rejects_non_http():
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("ftp://x.com/f") == ""


def test_same_domain():
    assert _is_same_domain("https://docs.example.com/a", "https://example.com/docs") is False
    assert _is_same_domain("https://example.com/b", "https://example.com/a") is True


def test_slugify_safe_filename():
    slug = _slugify("https://example.com/help/install-guide?x=1", "page")
    assert slug == "example.com_help_install-guide"
    assert "/" not in slug and "?" not in slug


def test_extract_links_resolves_relative_and_filters_noise():
    html = """
    <html><body>
      <a href="/docs/a">A</a>
      <a href="https://example.com/docs/b">B</a>
      <a href="mailto:x@y.com">mail</a>
      <a href="#anchor">anchor</a>
      <a href="javascript:void(0)">js</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com/help/")
    assert "https://example.com/docs/a" in links
    assert "https://example.com/docs/b" in links
    assert not any("mailto" in link or link.endswith("#anchor") or "javascript" in link for link in links)


@pytest.mark.asyncio
async def test_import_disabled_short_circuits(monkeypatch):
    """CONNECTOR_WEB_ENABLED=false → 直接返回跳过报告，不发起网络请求"""
    from app.config import get_settings
    from app.document.connectors.web_connector import import_from_web

    settings = get_settings()
    original = settings.web_connector.enabled
    settings.web_connector.enabled = False
    try:
        report = await import_from_web()
        assert report["skipped"] is True
        assert report["enabled"] is False
    finally:
        settings.web_connector.enabled = original
