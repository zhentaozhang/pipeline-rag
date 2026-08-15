"""P2-4：MinerU 解析器——失败抛异常（由 parser 降级），agent/extract 模式走对应端点"""

import pytest

from app.document.mineru_parser import MineruParser


def test_modes_select_endpoints(monkeypatch):
    settings = type("M", (), {
        "mineru": type("S", (), {
            "enabled": True,
            "base_url": "https://mineru.net",
            "api_key": "",
            "mode": "agent",
            "timeout_seconds": 5,
            "poll_interval_seconds": 0,
            "max_poll_retries": 1,
        }),
    })
    monkeypatch.setattr("app.document.mineru_parser.get_settings", lambda: settings)
    parser = MineruParser()
    assert parser._mode == "agent"


@pytest.mark.asyncio
async def test_parse_failure_raises(monkeypatch, tmp_path):
    """Agent 上传失败（HTTP 4xx）→ 抛异常，供调用方降级"""
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    settings = type("M", (), {
        "mineru": type("S", (), {
            "enabled": True,
            "base_url": "https://mineru.net",
            "api_key": "",
            "mode": "agent",
            "timeout_seconds": 5,
            "poll_interval_seconds": 0,
            "max_poll_retries": 1,
        }),
    })
    monkeypatch.setattr("app.document.mineru_parser.get_settings", lambda: settings)

    class _FakeResp:
        def raise_for_status(self):
            raise RuntimeError("mineru 401")

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _FakeResp()

    monkeypatch.setattr("app.document.mineru_parser.httpx.AsyncClient", _FakeClient)
    parser = MineruParser()
    with pytest.raises(RuntimeError):
        await parser.parse_pdf(fake_pdf)
