from typing import NamedTuple

from app.document.structure.patterns import (
    APPENDIX_PATTERN,
    CHAPTER_PATTERN,
    CHINESE_OUTLINE_PATTERN,
    DECIMAL_HEADING_PATTERN,
    EXPLICIT_STEP_PATTERN,
    MARKDOWN_HEADING_PATTERN,
    SINGLE_LEVEL_DIGIT_PATTERN,
)


class DocumentLineClassifier:
    class LineClassification(NamedTuple):
        kind: str
        level: int
        title: str
        raw_text: str

        def is_heading(self) -> bool:
            return self.kind == "HEADING"

    @classmethod
    def classify(cls, line: str) -> "LineClassification":
        normalized = (line or "").strip()
        if not normalized:
            return cls.LineClassification("BODY", 0, normalized, normalized)

        m = MARKDOWN_HEADING_PATTERN.match(normalized)
        if m:
            return cls.heading(len(m.group(1)), m.group(2).strip(), normalized)

        m = APPENDIX_PATTERN.match(normalized)
        if m:
            return cls.heading(1, normalized, normalized)

        m = EXPLICIT_STEP_PATTERN.match(normalized)
        if m:
            return cls.list_item(normalized)

        m = CHAPTER_PATTERN.match(normalized)
        if m:
            return cls.heading(2, normalized, normalized)

        m = DECIMAL_HEADING_PATTERN.match(normalized)
        if m:
            prefix = m.group(1)
            return cls.heading(len(prefix.split(".")), normalized, normalized)

        m = CHINESE_OUTLINE_PATTERN.match(normalized)
        if m:
            content = m.group(2).strip()
            if cls._looks_like_heading_content(content):
                return cls.heading(1, normalized, normalized)
            return cls.list_item(normalized)

        m = SINGLE_LEVEL_DIGIT_PATTERN.match(normalized)
        if m:
            content = m.group(2).strip()
            if cls._looks_like_heading_content(content):
                return cls.heading(1, normalized, normalized)
            return cls.list_item(normalized)

        if normalized.startswith(("- ", "* ", "+ ", "- [", "* [", "+ [")):
            return cls.list_item(normalized)

        return cls.LineClassification("BODY", 0, normalized, normalized)

    @classmethod
    def heading(cls, level: int, title: str, raw_text: str) -> "LineClassification":
        return cls.LineClassification(
            "HEADING", max(level, 1), (title or "").strip(), (raw_text or "").strip()
        )

    @classmethod
    def list_item(cls, raw_text: str) -> "LineClassification":
        return cls.LineClassification(
            "LIST_ITEM", 0, (raw_text or "").strip(), (raw_text or "").strip()
        )

    @classmethod
    def _looks_like_heading_content(cls, content: str) -> bool:
        normalized = (content or "").strip()
        if not normalized:
            return False
        if cls._ends_with_sentence_punctuation(normalized):
            return False
        if len(normalized) > 24:
            return False
        return not any(p in normalized for p in ("，", "；", "。", "："))

    @staticmethod
    def _ends_with_sentence_punctuation(text: str) -> bool:
        return text.endswith(("。", "！", "？", "；", ".", "!", "?", ";"))
