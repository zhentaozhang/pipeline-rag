"""
文档解析器
使用 Unstructured + MarkItDown，轻量化 Python 原生实现
"""

import asyncio
import re
from pathlib import Path
from typing import Any, NamedTuple

import structlog

logger = structlog.get_logger(__name__)

_SECTION_CODE_PATTERN = re.compile(
    r"^(第[一二三四五六七八九十百\d]+[章节条部分]\s*)|(\d+(?:\.\d+)+\s*)"
)


class ParseResult(NamedTuple):
    text: str  # 解析后的纯文本
    metadata: dict  # 文档元信息（标题、作者、页数等）
    file_type: str  # pdf / docx / pptx / txt / md
    nodes: list = []  # 文档结构节点 (List[DocumentStructureNodeCandidate])
    char_count: int = 0  # 总字符数
    token_count: int = 0  # 估算 token 数
    heading_count: int = 0  # 标题数量
    paragraph_count: int = 0  # 段落数量
    max_paragraph_length: int = 0  # 最长段落长度
    structure_level: int = 0  # 结构等级 (3=HIGH, 2=MEDIUM, 1=LOW, 0=UNKNOWN)
    content_quality_level: int = 0  # 内容质量 (3=HIGH, 2=MEDIUM, 1=LOW)


class DocumentParser:
    """
    多格式文档解析器。
    优先用 Unstructured 解析结构化文档（PDF/Word/PPT），
    Markdown/txt 直接读取，其余用 MarkItDown 兜底。
    """

    async def parse(self, file_path: str | Path, mime_type: str | None = None) -> ParseResult:
        path = Path(file_path)
        suffix = path.suffix.lower().lstrip(".")
        logger.info("parsing document", file=str(path), type=suffix)

        try:
            if suffix == "pdf":
                res = await self._parse_pdf(path)
            elif suffix == "docx":
                res = await self._parse_word(path)
            elif suffix == "doc":
                # 旧版 .doc 是二进制格式，非 ZIP；用 MarkItDown 兜底解析
                res = await self._parse_fallback(path)
            elif suffix == "pptx":
                res = await self._parse_ppt(path)
            elif suffix == "ppt":
                # 旧版 .ppt 是二进制 OLE2 格式，非 ZIP；用 MarkItDown 兜底解析
                res = await self._parse_fallback(path)
            elif suffix in ("md", "txt"):
                res = await self._parse_text(path)
            elif suffix in ("html", "htm"):
                res = await self._parse_html(path)
            else:
                res = await self._parse_fallback(path)
        except Exception:
            logger.warning(
                "structured parse failed, falling back to direct text parse",
                suffix=suffix,
                mime_type=mime_type,
                exc_info=True,
            )
            if suffix in ("md", "txt") or (mime_type and mime_type.startswith("text/")):
                res = await asyncio.to_thread(self._parse_text_direct, path)
            else:
                raise

        cleaned_text = self._cleanup_text(res.text)
        heading_count = self._count_headings(cleaned_text)

        from app.document.structure import DocumentStructurePipeline

        pipeline = DocumentStructurePipeline()
        doc_title = res.metadata.get("title") or path.stem
        nodes = await pipeline.extract(doc_title, cleaned_text)

        paragraphs = self._extract_paragraphs(cleaned_text)
        paragraph_count = len(paragraphs)
        max_paragraph_length = max((len(p) for p in paragraphs), default=0)

        char_count = len(cleaned_text)
        token_count = self._estimate_token_count(cleaned_text)
        structure_level = self._evaluate_structure_level(heading_count, paragraph_count)
        content_quality_level = self._evaluate_content_quality(cleaned_text, char_count)

        return ParseResult(
            text=cleaned_text,
            metadata=res.metadata,
            file_type=res.file_type,
            nodes=nodes,
            char_count=char_count,
            token_count=token_count,
            heading_count=heading_count,
            paragraph_count=paragraph_count,
            max_paragraph_length=max_paragraph_length,
            structure_level=structure_level,
            content_quality_level=content_quality_level,
        )

    # ── Text cleanup & analysis ──────────────────────────────────────────────

    @staticmethod
    def _cleanup_text(raw_text: str) -> str:
        if not raw_text:
            return ""
        cleaned = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = cleaned.replace("\x00", " ")
        cleaned = re.sub(r"[\t\x0b\f]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _count_headings(text: str) -> int:
        count = 0
        for line in text.split("\n"):
            stripped = line.strip()
            if (
                re.match(r"^#{1,6}\s", stripped)
                or re.match(r"^(第[一二三四五六七八九十百\d]+[章节条部分])", stripped)
                or re.match(r"^\d+(?:\.\d+)*\s+\S", stripped)
            ):
                count += 1
        return count

    @staticmethod
    def _extract_paragraphs(text: str) -> list[str]:
        return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        english_words = 0
        chinese_chars = 0
        for word in text.split():
            if re.search(r"[A-Za-z]", word):
                english_words += 1
        for ch in text:
            if "\u4e00" <= ch <= "\u9fa5":
                chinese_chars += 1
        return english_words + chinese_chars + max(1, (len(text) - chinese_chars) // 4)

    @staticmethod
    def _evaluate_structure_level(heading_count: int, paragraph_count: int) -> int:
        if heading_count >= 5:
            return 3  # HIGH
        if heading_count >= 2:
            return 2  # MEDIUM
        if paragraph_count >= 3:
            return 1  # LOW
        return 0  # UNKNOWN

    @staticmethod
    def _evaluate_content_quality(text: str, char_count: int) -> int:
        if not text or char_count < 20:
            return 1  # LOW
        broken_count = text.count("\ufffd")
        broken_ratio = broken_count / char_count if char_count else 1.0
        if broken_ratio > 0.02 or char_count < 100:
            return 1  # LOW
        if broken_ratio > 0.005 or char_count < 500:
            return 2  # MEDIUM
        return 3  # HIGH

    async def _parse_pdf(self, path: Path) -> ParseResult:
        """使用 Unstructured 解析 PDF"""
        from unstructured.partition.pdf import partition_pdf

        loop = asyncio.get_event_loop()

        def _do_parse():
            return partition_pdf(filename=str(path), strategy="auto")

        elements = await loop.run_in_executor(None, _do_parse)
        text = "\n\n".join([str(el) for el in elements])

        metadata = {}
        if elements:
            page_numbers = [
                getattr(el.metadata, "page_number", 1) for el in elements if hasattr(el, "metadata")
            ]
            page_numbers = [p for p in page_numbers if p is not None]
            if page_numbers:
                metadata["page_count"] = max(page_numbers)

        return ParseResult(text=text, metadata=metadata, file_type="pdf")

    async def _parse_word(self, path: Path) -> ParseResult:
        """使用 Unstructured 解析 Word 文档"""
        from unstructured.partition.docx import partition_docx

        loop = asyncio.get_event_loop()

        def _do_parse() -> list[object]:
            return partition_docx(filename=str(path))

        elements = await loop.run_in_executor(None, _do_parse)
        text = "\n\n".join([str(el) for el in elements])
        return ParseResult(text=text, metadata={}, file_type="docx")

    async def _parse_ppt(self, path: Path) -> ParseResult:
        """使用 Unstructured 解析 PowerPoint"""
        from unstructured.partition.pptx import partition_pptx

        loop = asyncio.get_event_loop()

        def _do_parse() -> list[object]:
            return partition_pptx(filename=str(path))

        elements = await loop.run_in_executor(None, _do_parse)
        text = "\n\n".join([str(el) for el in elements])
        return ParseResult(text=text, metadata={}, file_type="pptx")

    async def _parse_html(self, path: Path) -> ParseResult:
        """使用 MarkItDown 解析 HTML"""
        from markitdown import MarkItDown

        md = MarkItDown()
        loop = asyncio.get_event_loop()

        def _do_parse() -> Any:
            return md.convert(str(path))

        result = await loop.run_in_executor(None, _do_parse)
        return ParseResult(text=result.text_content or "", metadata={}, file_type="html")

    async def _parse_text(self, path: Path) -> ParseResult:
        """直接读取 Markdown/txt（不阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        try:
            text = await loop.run_in_executor(None, path.read_text, "utf-8")
        except UnicodeDecodeError:
            text = await loop.run_in_executor(None, path.read_text, "gbk")
        return ParseResult(text=text, metadata={}, file_type=path.suffix.lstrip("."))

    @staticmethod
    def _parse_text_direct(path: Path) -> ParseResult:
        """Tika 失败回退：直接按文本读取"""
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="gbk")
        return ParseResult(text=text, metadata={}, file_type=path.suffix.lstrip("."))

    async def _parse_fallback(self, path: Path) -> ParseResult:
        """使用 MarkItDown 兜底解析未知格式"""
        from markitdown import MarkItDown

        md = MarkItDown()
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(None, md.convert, str(path))
        return ParseResult(text=result.text_content or "", metadata={}, file_type="unknown")
