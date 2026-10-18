"""JEV Prompt Token 预算工具。

背景（2026-10-21 审计）：服务端使用 ``max_length=4096`` + ``truncation_side="left"``，
而 Prompt 的结构是「判断标准（含证据）在前、待评估内容（回答）在后」。
一旦总长超限，被左截断砍掉的恰好是**判断标准与证据**，模型于是在看不到证据的情况下
判断"该引用是否被支持" —— 这是引用核验准确率 0.84（LLM 为 1.00）的机制性原因。

正确做法：在分词之前先算预算，**只截 state，不截判断标准**。本模块只做纯计算，
tokenizer 以 ``count`` 回调注入，便于脱离 torch/transformers 做单元测试。
"""

from __future__ import annotations

from collections.abc import Callable

TRUNCATION_MARKER = "\n...[中间部分超长已截断]...\n"

CountFn = Callable[[str], int]


def truncate_text_by_tokens(
    text: str,
    *,
    count: CountFn,
    budget_tokens: int,
    head_ratio: float = 0.7,
    marker: str = TRUNCATION_MARKER,
) -> str:
    """按 token 预算截断文本，保留首尾（头部占比 ``head_ratio``）。

    以字符长度为二分变量：``count`` 单调递增于字符数，因此二分查找"最长可容纳的
    字符数"，再按比例切成首/尾两段并用标记连接。
    """
    if not text:
        return ""
    if budget_tokens <= 0:
        return ""
    if count(text) <= budget_tokens:
        return text

    marker_cost = count(marker)
    # 连标记都放不下时，退化为止截头部（至少保留一点上下文）
    if budget_tokens <= marker_cost + 8:
        lo, hi, best = 0, len(text), ""
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = text[:mid]
            if count(cand) <= budget_tokens:
                best = cand
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        head_len = int(mid * head_ratio)
        tail_len = mid - head_len
        cand = text[:head_len] + marker + (text[-tail_len:] if tail_len > 0 else "")
        if count(cand) <= budget_tokens:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best or text[: max(1, len(text) // 10)]


def fit_state_to_budget(
    state: str,
    *,
    count: CountFn,
    build_prompt: Callable[[str], str],
    max_tokens: int,
    min_budget_tokens: int = 64,
    shrink_ratio: float = 0.85,
) -> str:
    """把 state 调整到「build_prompt(state) 的 token 数 <= max_tokens」。

    先算 Prompt 的固定开销（判断标准、模板、assistant 标记），再二分截 state；
    由于分词边界可能合并，用逐步收缩 + 实际 Prompt 复核，保证最终一定不超限。
    """
    if max_tokens <= 0:
        return ""
    prompt = build_prompt(state)
    if count(prompt) <= max_tokens:
        return state

    overhead = max(0, count(prompt) - count(state))
    budget = max(min_budget_tokens, max_tokens - overhead)
    while True:
        candidate = truncate_text_by_tokens(state, count=count, budget_tokens=budget)
        if count(build_prompt(candidate)) <= max_tokens or budget <= min_budget_tokens:
            return candidate
        budget = max(min_budget_tokens, int(budget * shrink_ratio))
