"""P3-8 迭代式多跳检索：把"检索 → 生成下一跳查询 → 再检索"的循环抽成可注入的纯逻辑。

设计（安全第一）：
- 默认关（``settings.rag.iterative_multi_hop_enabled``）；
- 循环体不依赖任何外部实现——``next_query_fn`` / ``retrieve_fn`` / ``merge_fn`` 全部注入，
  便于离线单测（无 LLM、无 DB、无网络）；
- 收敛信号来自 ``next_query_fn``：返回空串或与上一跳相同即停止（等价于"证据已足够"）；
- 任一环节抛异常 → 立即停止并返回已累积的结果，绝不向外抛（检索主链路不会被打断）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def iterate_hops(
    base_question: str,
    initial_context: Any,
    *,
    max_hops: int,
    next_query_fn: Callable[[str, Any], Awaitable[str]],
    retrieve_fn: Callable[[str], Awaitable[Any]],
    merge_fn: Callable[[Any, Any], Any],
) -> tuple[Any, int]:
    """执行至多 ``max_hops`` 跳的迭代检索，返回 (累积后的上下文, 实际跳数)。

    跳数定义：初始检索 = 1 跳；每追加一跳 +1。
    """
    context = initial_context
    question = (base_question or "").strip()
    hops = 1

    for _ in range(max(0, int(max_hops) - 1)):
        try:
            nxt = await next_query_fn(question, context)
        except Exception:  # noqa: BLE001 — 生成下一跳失败即收敛
            break
        nxt = (nxt or "").strip()
        if not nxt or nxt == question:
            break
        question = nxt
        try:
            extra = await retrieve_fn(nxt)
        except Exception:  # noqa: BLE001 — 单跳检索失败即收敛
            break
        context = merge_fn(context, extra)
        hops += 1

    return context, hops
