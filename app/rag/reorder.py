"""P2-7 LongContextReorder：缓解 LLM "lost in the middle"（Liu et al. 2023）。

LLM 对上下文的**首尾**注意力最强、**中部**最弱。把已按相关度降序排列的证据重排为
"最相关的落在首尾、最不相关的堆到中部"，可在不增加任何 token 成本的前提下提升证据利用率。

与既有"抽取式压缩"（``_trim_snippet`` / ``_extract_soft_window`` / PromptBudget）互补：
本模块只改**顺序**，不改内容。
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def reorder_long_context(items: list[T]) -> list[T]:
    """把相关度降序列表重排为 [1st, 3rd, 5th, …, worst, …, 4th, 2nd]。

    首元素为最相关、末元素为次相关；最不相关的落在中部。长度 < 3 时原样返回（重排无意义）。
    """
    n = len(items)
    if n < 3:
        return list(items)
    left = items[0::2]  # 第 1、3、5… 相关
    right = items[1::2]  # 第 2、4、6… 相关
    return list(left) + list(right)[::-1]
