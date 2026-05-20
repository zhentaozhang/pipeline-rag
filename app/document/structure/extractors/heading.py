from app.document.structure.line_classifier import DocumentLineClassifier
from app.document.structure.models import DocumentStructureSignalKind
from app.document.structure.patterns import (
    APPENDIX_PATTERN,
    CHAPTER_PATTERN,
    DECIMAL_HEADING_PATTERN,
    MARKDOWN_HEADING_PATTERN,
)


def classify_markdown_heading(extractor, document_title, normalized, indent, line_no, raw_text):
    m = MARKDOWN_HEADING_PATTERN.match(normalized)
    if not m:
        return None
    title = m.group(2).strip()
    if extractor._same_document_title(document_title, title):
        return extractor._signal(
            line_no,
            raw_text,
            normalized,
            indent,
            DocumentStructureSignalKind.NOISE,
            title=title,
            reasons=["duplicate-document-title"],
            confidence=0.99,
        )
    code = extractor._extract_code(title)
    signal = extractor._signal(
        line_no,
        raw_text,
        normalized,
        indent,
        DocumentStructureSignalKind.HEADING,
        code=code,
        title=title,
        level_hint=len(m.group(1)),
        reasons=["markdown-heading"],
        confidence=0.98,
    )
    signal.numeric_path = extractor._extract_numeric_path(signal.node_code)
    return signal


def classify_chapter_heading(extractor, document_title, normalized, indent, line_no, raw_text):
    m = CHAPTER_PATTERN.match(normalized)
    if not m:
        return None
    code = m.group(1).strip()
    title = m.group(3).strip()
    if extractor._same_document_title(document_title, title):
        return extractor._signal(
            line_no,
            raw_text,
            normalized,
            indent,
            DocumentStructureSignalKind.NOISE,
            code=code,
            title=title,
            reasons=["duplicate-document-title"],
            confidence=0.99,
        )
    signal = extractor._signal(
        line_no,
        raw_text,
        normalized,
        indent,
        DocumentStructureSignalKind.HEADING,
        code=code,
        title=title,
        level_hint=1,
        reasons=["chapter-heading"],
        confidence=0.96,
    )
    chapter_no = extractor._parse_loose_number(m.group(2))
    if chapter_no and chapter_no > 0:
        signal.numeric_path = [chapter_no]
    return signal


def classify_appendix_heading(extractor, normalized, indent, line_no, raw_text):
    m = APPENDIX_PATTERN.match(normalized)
    if not m:
        return None
    code = m.group(1).strip()
    title = (m.group(3) or code).strip()
    return extractor._signal(
        line_no,
        raw_text,
        normalized,
        indent,
        DocumentStructureSignalKind.HEADING,
        code=code,
        title=title,
        level_hint=1,
        reasons=["appendix-heading"],
        confidence=0.92,
    )


def classify_decimal_heading(extractor, normalized, indent, line_no, raw_text):
    m = DECIMAL_HEADING_PATTERN.match(normalized)
    if not m:
        return None
    code = m.group(1).strip()
    title = m.group(2).strip()
    signal = extractor._signal(
        line_no,
        raw_text,
        normalized,
        indent,
        DocumentStructureSignalKind.HEADING,
        code=code,
        title=title,
        level_hint=max(1, len(code.split("."))),
        reasons=["decimal-heading"],
        confidence=0.95,
    )
    signal.numeric_path = extractor._extract_numeric_path(code)
    return signal


def classify_plain_heading_candidate(extractor, normalized, indent, line_no, raw_text, context):

    fallback = DocumentLineClassifier.classify(normalized)
    if fallback.is_heading() or not extractor._looks_like_plain_heading(normalized, context):
        return None
    return extractor._signal(
        line_no,
        raw_text,
        normalized,
        indent,
        DocumentStructureSignalKind.HEADING_CANDIDATE,
        title=normalized,
        level_hint=extractor._infer_plain_heading_level(context),
        reasons=["plain-heading-candidate"],
        confidence=0.58,
    )
