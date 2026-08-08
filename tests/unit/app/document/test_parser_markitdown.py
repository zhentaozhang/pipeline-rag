"""C7 TDD：MarkItDown 解析路径往返回归（HTML/兜底路径）。

升级 markitdown 0.1.6 → 0.3.x 时，此测试锁定 convert 路径行为：
解析结果非空且包含关键文本。若 0.3 API 变化（convert 返回对象/入口改名），
本测试将 RED，需适配 app/document/parser.py 后恢复 GREEN。
"""

from pathlib import Path

from app.document.parser import DocumentParser


async def test_parse_html_via_markitdown_returns_text(tmp_path: Path):
    html = tmp_path / "sample.html"
    html.write_text("<html><body><h1>标题</h1><p>段落内容</p></body></html>", encoding="utf-8")

    result = await DocumentParser()._parse_html(html)

    assert result.file_type == "html"
    assert result.text
    assert "标题" in result.text
    assert "段落内容" in result.text


async def test_parse_fallback_via_markitdown_returns_text(tmp_path: Path):
    htm = tmp_path / "sample.htm"
    htm.write_text("<html><body><h2>副标题</h2><p>兜底内容</p></body></html>", encoding="utf-8")

    result = await DocumentParser()._parse_fallback(htm)

    assert result.file_type == "unknown"
    assert result.text
    assert "副标题" in result.text
    assert "兜底内容" in result.text
