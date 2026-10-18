"""编号类 token 抽取：把"条款号/子条款号/文档名/职级/城市类别"从文本里拆出来。

为什么单独一个模块：这些值是**闭集精确值**，应该用 keyword 字段 + term 查询，
而不是丢进全文检索让分词器去切。中文数字（"第九条"）与阿拉伯数字统一成字符串，
避免同一语义出现两种写法。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CN_DIGIT = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_CLAUSE_RE = re.compile(r"第\s*(\d{1,3}|[零一二三四五六七八九十]{1,3})\s*条")
_SUBCLAUSE_RE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2})(?![\d.])")
_DOC_NAME_RE = re.compile(r"《([^》]{4,60})》")
_GRADE_RE = re.compile(r"(?<![A-Za-z0-9])(M[1-9]\+?|P[1-9](?:-\d+)?)(?![A-Za-z0-9])")
_CITY_CLASS_RE = re.compile(r"([A-D])\s*类城市")
_SUBCLAUSE_BOLD_RE = re.compile(r"\*\*(\d{1,2}\.\d{1,2})")


def cn_to_int(text: str) -> int | None:
    """把 '9' / '九' / '十二' / '二十三' 转成 int；无法解析返回 None。"""
    value = (text or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if any(ch not in _CN_DIGIT and ch != "十" for ch in value):
        return None
    if "十" in value:
        head, _, tail = value.partition("十")
        tens = _CN_DIGIT.get(head, 1) if head else 1
        ones = _CN_DIGIT.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return _CN_DIGIT.get(value)


@dataclass(frozen=True)
class QueryTokens:
    clauses: list[str] = field(default_factory=list)
    subclauses: list[str] = field(default_factory=list)
    doc_names: list[str] = field(default_factory=list)
    grades: list[str] = field(default_factory=list)
    city_classes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            (self.clauses, self.subclauses, self.doc_names, self.grades, self.city_classes)
        )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def extract_query_tokens(text: str) -> QueryTokens:
    raw = text or ""
    clauses = [str(n) for n in (cn_to_int(m) for m in _CLAUSE_RE.findall(raw)) if n is not None]
    return QueryTokens(
        clauses=_dedupe(clauses),
        subclauses=_dedupe(_SUBCLAUSE_RE.findall(raw)),
        doc_names=_dedupe(_DOC_NAME_RE.findall(raw)),
        grades=_dedupe(_GRADE_RE.findall(raw)),
        city_classes=_dedupe(_CITY_CLASS_RE.findall(raw)),
    )


def derive_chunk_tokens(section_path: str | None, chunk_text: str | None) -> dict[str, list[str]]:
    """索引侧：从章节路径与正文推导派生字段值（写入 ES keyword 字段）。"""
    path = section_path or ""
    body = chunk_text or ""
    clauses = [str(n) for n in (cn_to_int(m) for m in _CLAUSE_RE.findall(path)) if n is not None]
    subclauses = _SUBCLAUSE_BOLD_RE.findall(body) or _SUBCLAUSE_RE.findall(body)
    return {
        "clauseNumber": _dedupe(clauses),
        "subClauseNumbers": _dedupe(list(subclauses)),
        "gradeCodes": _dedupe(_GRADE_RE.findall(body)),
        "cityClasses": _dedupe(_CITY_CLASS_RE.findall(body)),
    }
