"""证据元数据工具：章节路径解析等跨通道复用的纯函数。

检索通道（pgvector / Elasticsearch）与父块提升都会拿到 ``section_path``，
但下游 Prompt 渲染需要"叶子章节标题"这类派生字段。把解析规则收敛到一处，
避免各通道各自 split 出不同的结果。
"""

from __future__ import annotations

# 兼容中英文层级分隔符：报告里同时出现过 "1. 总则 > 1.2 试用期"、
# "第一章/第二节"、"A › B" 三种写法。
_SECTION_SEPARATORS: tuple[str, ...] = ("›", "»", "／", "/", ">", "\\", "|")
_SPLIT_SENTINEL = "\x00"


def leaf_section_title(section_path: str | None) -> str | None:
    """取章节路径的叶子标签。

    ``'1. 总则 > 1.2 试用期'`` -> ``'1.2 试用期'``；
    空串、纯分隔符、None -> ``None``。
    """
    if not section_path:
        return None
    text = section_path
    for separator in _SECTION_SEPARATORS:
        text = text.replace(separator, _SPLIT_SENTINEL)
    parts = [part.strip() for part in text.split(_SPLIT_SENTINEL) if part.strip()]
    return parts[-1] if parts else None
