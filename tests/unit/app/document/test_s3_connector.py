"""P3-3：S3 连接器——文件类型过滤与禁用时的短路"""

import pytest

from app.document.connectors.base import DocumentConnector


class _DummyConnector(DocumentConnector):
    async def list_files(self):
        return []

    async def fetch_to_local(self, file, dest_dir):
        return dest_dir / file.name


def test_supports_extension_filter():
    c = _DummyConnector()
    allowed = [".pdf", ".docx", ".txt"]
    assert c.supports("手册.pdf", allowed)
    assert c.supports("说明.DOCX", allowed)  # 大小写不敏感
    assert c.supports("readme.txt", allowed)
    assert not c.supports("data.xlsx", allowed)
    assert not c.supports("noext", allowed)


def test_supports_empty_allows_all():
    c = _DummyConnector()
    assert c.supports("anything.bin", [])


@pytest.mark.asyncio
async def test_import_disabled_short_circuits(monkeypatch):
    """CONNECTOR_S3_ENABLED=false → 直接返回跳过报告，不访问 S3"""
    from app.config import get_settings
    from app.document.connectors.s3_connector import import_from_s3

    settings = get_settings()
    original = settings.s3_connector.enabled
    settings.s3_connector.enabled = False
    try:
        report = await import_from_s3()
        assert report["skipped"] is True
        assert report["enabled"] is False
    finally:
        settings.s3_connector.enabled = original
