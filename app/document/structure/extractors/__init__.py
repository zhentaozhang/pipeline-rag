import re

from app.common.utils import safe_int
from app.config import get_settings
from app.document.structure.extractors.base import (
    LineContext,
    build_context,
    build_line_frequency,
    build_logical_lines,
    safe_text,
)
from app.document.structure.extractors.heading import (
    classify_appendix_heading,
    classify_chapter_heading,
    classify_decimal_heading,
    classify_markdown_heading,
    classify_plain_heading_candidate,
)
from app.document.structure.line_classifier import DocumentLineClassifier
from app.document.structure.models import (
    DocumentStructureLogicalLine,
    DocumentStructureSignal,
    DocumentStructureSignalBatch,
    DocumentStructureSignalKind,
)
from app.document.structure.patterns import (
    APPENDIX_PATTERN,
    BULLET_PATTERN,
    CHAPTER_PATTERN,
    CHECKBOX_PATTERN,
    CHINESE_OUTLINE_PATTERN,
    COPYRIGHT_NOISE_PATTERN,
    DECIMAL_HEADING_PATTERN,
    EXPLICIT_STEP_PATTERN,
    PAGE_NOISE_PATTERN,
    SINGLE_LEVEL_DIGIT_PATTERN,
    TABLE_SPLIT_PATTERN,
    VERSION_FOOTER_PATTERN,
)


class DocumentStructureSignalExtractor:
    """提取文档结构的原子信号"""

    def __init__(self) -> None:
        self.properties = get_settings().structure

    def extract(self, document_title: str, parsed_text: str) -> DocumentStructureSignalBatch:
        normalized_title = safe_text(document_title)
        logical_lines = build_logical_lines(parsed_text)
        line_frequency = build_line_frequency(logical_lines)
        signals = []

        if normalized_title:
            signals.append(
                DocumentStructureSignal(
                    line_no=0,
                    raw_text=normalized_title,
                    normalized_text=normalized_title,
                    kind=DocumentStructureSignalKind.DOCUMENT_TITLE,
                    title=normalized_title,
                    level_hint=0,
                    confidence=1.0,
                )
            )

        for index, logical_line in enumerate(logical_lines):
            context = build_context(logical_lines, index)
            signals.append(self._classify(normalized_title, logical_line, context, line_frequency))

        context_lines = [line.normalized_text for line in logical_lines]
        return DocumentStructureSignalBatch(context_lines=context_lines, signals=signals)

    def _classify(
        self,
        document_title: str,
        logical_line: DocumentStructureLogicalLine,
        context: LineContext,
        line_frequency: dict[str, int],
    ) -> DocumentStructureSignal:
        line_no = logical_line.line_no
        raw_text = logical_line.raw_text
        normalized = logical_line.normalized_text
        indent = logical_line.indent_level

        if not normalized:
            return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.BLANK, confidence=1.0)

        result = self._classify_noise(document_title, normalized, indent, line_frequency, line_no, raw_text)
        if result is not None:
            return result

        result = classify_markdown_heading(self, document_title, normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = self._classify_explicit_step(normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = classify_chapter_heading(self, document_title, normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = classify_appendix_heading(self, normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = classify_decimal_heading(self, normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = self._classify_table_row(normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = self._classify_quote(normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = self._classify_checkbox(normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = self._classify_bullet(normalized, indent, line_no, raw_text)
        if result is not None:
            return result

        result = self._classify_single_level_digit(normalized, indent, line_no, raw_text, context)
        if result is not None:
            return result

        result = self._classify_chinese_outline(normalized, indent, line_no, raw_text, context)
        if result is not None:
            return result

        result = classify_plain_heading_candidate(self, normalized, indent, line_no, raw_text, context)
        if result is not None:
            return result

        return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.BODY, title=normalized, reasons=["body"], confidence=1.0)

    def _classify_noise(self, document_title, normalized, indent, line_frequency, line_no, raw_text):
        freq = line_frequency.get(normalized, 0)
        if self._is_repeated_noise(document_title, normalized, freq):
            return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.NOISE, reasons=["repeated-running-header-or-footer"], confidence=0.99)
        if PAGE_NOISE_PATTERN.match(normalized):
            return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.NOISE, reasons=["page-noise"], confidence=0.98)
        return None

    def _classify_explicit_step(self, normalized, indent, line_no, raw_text):
        m = EXPLICIT_STEP_PATTERN.match(normalized)
        if not m:
            return None
        item_index = self._parse_loose_number(m.group(1) or m.group(2))
        return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.STEP_ITEM, title=m.group(3).strip(), item_index=item_index, reasons=["explicit-step"], confidence=0.96)

    def _classify_table_row(self, normalized, indent, line_no, raw_text):
        if not self._is_table_row(normalized):
            return None
        return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.TABLE_ROW, title=normalized, reasons=["table-row"], confidence=0.90)

    def _classify_quote(self, normalized, indent, line_no, raw_text):
        if not normalized.startswith(">"):
            return None
        return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.QUOTE, title=normalized, reasons=["quote"], confidence=0.88)

    def _classify_checkbox(self, normalized, indent, line_no, raw_text):
        m = CHECKBOX_PATTERN.match(normalized)
        if not m:
            return None
        return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.LIST_ITEM, title=m.group(1).strip(), reasons=["checkbox-list"], confidence=0.92)

    def _classify_bullet(self, normalized, indent, line_no, raw_text):
        m = BULLET_PATTERN.match(normalized)
        if not m:
            return None
        return self._signal(line_no, raw_text, normalized, indent, DocumentStructureSignalKind.LIST_ITEM, title=m.group(2).strip(), reasons=["bullet-list"], confidence=0.90)

    def _classify_single_level_digit(self, normalized, indent, line_no, raw_text, context):
        m = SINGLE_LEVEL_DIGIT_PATTERN.match(normalized)
        if not m:
            return None
        title = m.group(2).strip()
        item_index = self._parse_loose_number(m.group(1))
        sequential = self._is_neighbor_sequence(item_index, "ARABIC_SINGLE", context)
        introduced = self._previous_introduces_list(context.previous_non_blank)
        heading_like = not sequential and not introduced and self._looks_like_plain_heading(title, context)
        kind = DocumentStructureSignalKind.HEADING_CANDIDATE if heading_like else DocumentStructureSignalKind.LIST_ITEM
        reason = "single-digit-ambiguous-heading" if heading_like else ("single-digit-sequence-list" if sequential else "single-digit-list")
        conf = 0.62 if heading_like else (0.93 if sequential or introduced else 0.88)
        signal = self._signal(line_no, raw_text, normalized, indent, kind, code=m.group(1).strip(), title=title, level_hint=1 if heading_like else None, item_index=item_index, reasons=[reason], confidence=conf)
        if heading_like and item_index and item_index > 0:
            signal.numeric_path = [item_index]
        return signal

    def _classify_chinese_outline(self, normalized, indent, line_no, raw_text, context):
        m = CHINESE_OUTLINE_PATTERN.match(normalized)
        if not m:
            return None
        title = m.group(2).strip()
        item_index = self._parse_loose_number(m.group(1))
        sequential = self._is_neighbor_sequence(item_index, "CHINESE_OUTLINE", context)
        introduced = self._previous_introduces_list(context.previous_non_blank)
        heading_like = not sequential and not introduced and self._looks_like_plain_heading(title, context)
        kind = DocumentStructureSignalKind.HEADING_CANDIDATE if heading_like else DocumentStructureSignalKind.LIST_ITEM
        reason = "chinese-outline-ambiguous-heading" if heading_like else ("chinese-outline-sequence-list" if sequential else "chinese-outline-list")
        conf = 0.60 if heading_like else (0.92 if sequential or introduced else 0.86)
        signal = self._signal(line_no, raw_text, normalized, indent, kind, code=m.group(1).strip(), title=title, level_hint=1 if heading_like else None, item_index=item_index, reasons=[reason], confidence=conf)
        if heading_like and item_index and item_index > 0:
            signal.numeric_path = [item_index]
        return signal

    def _signal(
        self,
        line_no: int,
        raw_text: str,
        normalized: str,
        indent_level: int,
        kind: DocumentStructureSignalKind,
        code: str = "",
        title: str = "",
        level_hint: int | None = None,
        item_index: int | None = None,
        reasons: list[str] = None,
        confidence: float = 1.0,
    ) -> DocumentStructureSignal:
        return DocumentStructureSignal(
            line_no=line_no,
            raw_text=raw_text,
            normalized_text=normalized,
            kind=kind,
            node_code=code,
            title=title or normalized,
            level_hint=level_hint,
            indent_level=indent_level,
            item_index=item_index,
            reasons=reasons or [],
            confidence=confidence,
        )

    def _extract_code(self, title: str) -> str:
        m = DECIMAL_HEADING_PATTERN.match(title)
        if m:
            return m.group(1).strip()
        m = CHAPTER_PATTERN.match(title)
        if m:
            return m.group(1).strip()
        m = APPENDIX_PATTERN.match(title)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_numeric_path(self, code: str) -> list[int]:
        normalized = safe_text(code)
        if not normalized:
            return []
        if "." in normalized:
            segments = normalized.split(".")
            if all(s.isdigit() for s in segments):
                return [safe_int(s) for s in segments]
            return []
        m = CHAPTER_PATTERN.search(normalized + " 标题")
        if m:
            chapter_no = self._parse_loose_number(m.group(2))
            if chapter_no and chapter_no > 0:
                return [chapter_no]
        return []

    def _is_table_row(self, normalized: str) -> bool:
        if normalized.startswith("|") and normalized.endswith("|"):
            return True
        if "\t" in normalized:
            return True
        if len(TABLE_SPLIT_PATTERN.split(normalized)) >= 3 and "|" in normalized:
            return True
        return bool(re.match(r"^[:\-\s|]+$", normalized))

    def _looks_like_plain_heading(self, text: str, context: LineContext) -> bool:
        normalized = safe_text(text)
        if not normalized or len(normalized) > self.properties.max_plain_heading_chars:
            return False
        if DocumentLineClassifier._ends_with_sentence_punctuation(normalized):
            return False
        if "http://" in normalized or "https://" in normalized:
            return False
        if normalized.startswith("|") or normalized.endswith("|"):
            return False
        if re.match(r"^[\-=_]{3,}$", normalized):
            return False

        isolated = context.blank_before or context.blank_after
        next_looks_content = bool(
            context.next_non_blank
            and context.next_non_blank.normalized_text
            and not re.match(r"^[:\-\s|]+$", context.next_non_blank.normalized_text)
        )
        noun_like = not any(
            p in normalized for p in ("，", "；", "。", "：")
        ) and not normalized.lower().startswith("http")
        return isolated and next_looks_content and noun_like

    def _infer_plain_heading_level(self, context: LineContext) -> int:
        if not context or context.blank_before:
            return 1
        return 2

    def _is_repeated_noise(self, document_title: str, normalized: str, frequency: int) -> bool:
        if frequency < 2 or not normalized:
            return False
        if self._same_document_title(document_title, normalized):
            return True
        if COPYRIGHT_NOISE_PATTERN.match(normalized):
            return True
        return (
            frequency >= 3
            and len(normalized) <= 120
            and (bool(VERSION_FOOTER_PATTERN.match(normalized)) or "|" in normalized)
        )

    def _same_document_title(self, document_title: str, candidate: str) -> bool:
        left = self._normalize_comparable_title(document_title)
        right = self._normalize_comparable_title(candidate)
        return bool(left and left == right)

    def _normalize_comparable_title(self, text: str) -> str:
        normalized = safe_text(text)
        if not normalized:
            return ""
        normalized = re.sub(r"^#+\s*", "", normalized)
        normalized = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", normalized)
        normalized = re.sub(r"\s+", "", normalized)
        return normalized.lower()

    def _previous_introduces_list(self, prev_non_blank: DocumentStructureLogicalLine | None) -> bool:
        if not prev_non_blank:
            return False
        prev = safe_text(prev_non_blank.normalized_text)
        return prev.endswith("：") or prev.endswith(":")

    def _is_neighbor_sequence(self, item_index: int | None, family: str, context: LineContext) -> bool:
        if item_index is None:
            return False
        return self._is_sequence_neighbor(
            context.previous_non_blank, item_index, family, -1
        ) or self._is_sequence_neighbor(context.next_non_blank, item_index, family, 1)

    def _is_sequence_neighbor(
        self, cand: DocumentStructureLogicalLine | None, item_index: int, family: str, offset: int
    ) -> bool:
        if not cand:
            return False
        cand_index = self._resolve_ordered_index(cand.normalized_text, family)
        return cand_index is not None and cand_index == item_index + offset

    def _resolve_ordered_index(self, text: str, family: str) -> int | None:
        normalized = safe_text(text)
        if not normalized:
            return None
        if family == "ARABIC_SINGLE":
            m = SINGLE_LEVEL_DIGIT_PATTERN.match(normalized)
            return self._parse_loose_number(m.group(1)) if m else None
        elif family == "CHINESE_OUTLINE":
            m = CHINESE_OUTLINE_PATTERN.match(normalized)
            return self._parse_loose_number(m.group(1)) if m else None
        return None

    def _parse_loose_number(self, text: str) -> int | None:
        normalized = safe_text(text)
        if not normalized:
            return None
        res = safe_int(normalized, default=None)
        if res is not None:
            return res
        digit_map = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9,
        }
        if normalized == "十":
            return 10
        if normalized.startswith("十") and len(normalized) == 2:
            return 10 + digit_map.get(normalized[1], 0)
        if normalized.endswith("十") and len(normalized) == 2:
            return digit_map.get(normalized[0], 0) * 10
        if "十" in normalized and len(normalized) == 3:
            return digit_map.get(normalized[0], 0) * 10 + digit_map.get(normalized[2], 0)
        return digit_map.get(normalized[0])
