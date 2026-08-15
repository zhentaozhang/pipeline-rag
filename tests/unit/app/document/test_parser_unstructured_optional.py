"""unstructured 可选化（第二轮架构评审·可以优化 6）：缺失时降级 markitdown"""

from pathlib import Path

import pytest

from app.document.parser import DocumentParser, _unstructured_available


def test_unstructured_detection():
    """本测试环境应无 unstructured（已移出主依赖）——验证降级路径真实生效"""
    assert _unstructured_available() is False


@pytest.mark.asyncio
async def test_pdf_falls_back_to_markitdown(tmp_path: Path):
    """unstructured 缺失时 PDF 走 markitdown 降级（无报错）"""
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake minimal")

    result = await DocumentParser()._parse_pdf(pdf)
    assert result.file_type == "pdf"
    assert isinstance(result.text, str)  # 空内容也返回（非抛错）


@pytest.mark.asyncio
async def test_word_falls_back_to_markitdown(tmp_path: Path):
    docx = tmp_path / "sample.docx"
    docx.write_bytes(b"PK\x03\x04 fake docx")

    result = await DocumentParser()._parse_word(docx)
    assert result.file_type == "docx"


@pytest.mark.asyncio
async def test_ppt_falls_back_to_markitdown(tmp_path: Path):
    pptx = tmp_path / "sample.pptx"
    pptx.write_bytes(b"PK\x03\x04 fake pptx")

    result = await DocumentParser()._parse_ppt(pptx)
    assert result.file_type == "pptx"


@pytest.mark.asyncio
async def test_unavailable_raises_with_hint_when_markitdown_fails(tmp_path: Path):
    """markitdown 降级也失败时给出安装提示（错误信息包含可选依赖说明）"""
    from unittest.mock import patch

    docx = tmp_path / "bad.docx"
    docx.write_bytes(b"garbage")

    def _boom(path: str) -> None:
        raise RuntimeError("markitdown convert exploded")

    with (
        patch("app.document.parser._unstructured_available", return_value=False),
        patch("markitdown.MarkItDown.convert", _boom),
    ):
        with pytest.raises(RuntimeError) as exc:
            await DocumentParser()._parse_word(docx)
        assert "full-parsing" in str(exc.value) or "MinerU" in str(exc.value)
