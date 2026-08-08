from __future__ import annotations

import re

_NUMERAL_MAP = {
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
    "十": "10",
}


def normalize_step_numeral(text: str) -> str:
    def _cn_to_arabic(m: re.Match) -> str:
        cn = m.group(2)
        suffix = m.group(3)
        arabic = _NUMERAL_MAP.get(cn)
        if arabic:
            return f"第{arabic}{suffix}"
        return str(m.group(0))

    return re.sub(r"(第)([零〇一二三四五六七八九十])(步|个步骤|条|项|点)", _cn_to_arabic, text)


def normalize_text(text: str) -> str:
    val = (text or "").strip()
    if not val:
        return ""
    return re.sub(r"[\s>`*#_\-，,。；;：:（）()\u201c\u201d\"'\[\]？！…～%]+", "", val).lower()


def first_non_blank(primary: str | None, fallback: str) -> str:
    if primary is not None and primary.strip():
        return primary.strip()
    return fallback


def safe_text(text: str | None) -> str:
    return (text or "").strip()


def clip_head(text: str, max_chars: int) -> str:
    normalized = safe_text(text)
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 1:
        return ""
    return normalized[: max_chars - 1] + "…"


def clip_tail(text: str, max_chars: int) -> str:
    normalized = safe_text(text)
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 1:
        return ""
    start = max(0, len(normalized) - (max_chars - 1))
    return "…" + normalized[start:]


def join_non_blank(left: str, right: str) -> str:
    if not left or not left.strip():
        return safe_text(right)
    if not right or not right.strip():
        return safe_text(left)
    return f"{left.strip()}\n\n{right.strip()}"
