"""证据元数据工具单测：章节路径叶子标签解析。"""

from __future__ import annotations

import pytest

from app.rag.evidence_meta import leaf_section_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1. 总则 > 1.2 试用期", "1.2 试用期"),
        ("第一章 / 第二节 / 试用期", "试用期"),
        ("A › B › C", "C"),
        ("总则／附则", "附则"),
        ("单段章节", "单段章节"),
        ("  收尾带分隔符 >  ", "收尾带分隔符"),
        ("", None),
        ("   ", None),
        ("> » ›", None),
        (None, None),
    ],
)
def test_leaf_section_title_variants(raw: str | None, expected: str | None) -> None:
    assert leaf_section_title(raw) == expected
