"""LLM streaming with tool calling helper for RAG executor"""

import json
from collections.abc import AsyncIterator
from typing import Any

import structlog

from app.common.llm_client import get_chat_client
from app.common.sse import SSEEventType
from app.config import get_settings
from app.executors.rag_safety import _SAFETY_PLACEHOLDER, check_chunk_safety
from app.observability.metrics import LLM_FINISH_REASON_TOTAL

logger = structlog.get_logger(__name__)
settings = get_settings()


def extract_text(chunk: str) -> str:
    """从 SSE 事件字符串中提取纯文本内容"""
    if chunk.startswith("data: "):
        try:
            data = json.loads(chunk[6:].strip())
            return str(data.get("content", chunk))
        except (json.JSONDecodeError, ValueError):
            return chunk
    return chunk


async def run_output_filter(text: str):
    from app.safety.output import OutputFilter

    return await OutputFilter().filter(text)


async def stream_llm_with_tools(
    task, system_prompt: str, user_prompt: str, emit_fn
) -> AsyncIterator[str]:
    """
    LLM 流式调用（支持 tool calling）。
    首轮流式输出 text，同时收集 tool_call delta；
    若无工具调用则直接结束（零额外延迟）；
    若有工具调用则执行工具后第二轮流式输出。
    """
    from app.agent.tools.code_executor import code_executor as _code_executor_fn
    from app.chat.support import is_dashscope_provider, resolve_provider

    openai = get_chat_client()

    tool_def = {
        "type": "function",
        "function": {
            "name": "code_executor",
            "description": "执行 Python 代码并返回运行结果。适用于数据分析、数值计算、格式转换等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 代码"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 10"},
                },
                "required": ["code"],
            },
        },
    }

    base_kwargs: dict = {
        "model": settings.llm.model,
        "temperature": settings.llm.temperature,
        "max_tokens": settings.llm.max_tokens,
        "timeout": settings.llm.timeout_seconds,
        "stream": True,
    }
    if not is_dashscope_provider(resolve_provider(settings.llm.base_url)):
        base_kwargs["stream_options"] = {"include_usage": True}

    stream = await openai.chat.completions.create(
        **base_kwargs,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[tool_def],
    )
    task.model_call_count += 1

    text_buffer: list[str] = []
    tool_calls: dict[int, dict] = {}

    last_finish_reason: str = ""
    async for event in stream:
        if not event.choices:
            if hasattr(event, "usage") and event.usage:
                task.add_token_usage(
                    event.usage.prompt_tokens or 0,
                    event.usage.completion_tokens or 0,
                )
            continue

        delta = event.choices[0].delta
        finish_reason = event.choices[0].finish_reason
        if finish_reason:
            last_finish_reason = finish_reason

        if delta.content:
            block_reason = check_chunk_safety(delta.content)
            safe = _SAFETY_PLACEHOLDER if block_reason else delta.content
            text_buffer.append(safe)
            yield emit_fn(SSEEventType.TEXT, safe)

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls:
                    tool_calls[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                if tc_delta.id:
                    tool_calls[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls[idx]["function"]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

        if hasattr(event, "usage") and event.usage:
            task.add_token_usage(
                event.usage.prompt_tokens or 0,
                event.usage.completion_tokens or 0,
            )

    if last_finish_reason:
        LLM_FINISH_REASON_TOTAL.labels(
            model=settings.llm.model, reason=last_finish_reason
        ).inc()

    if not tool_calls:
        return

    first_pass_text = "".join(text_buffer)

    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": first_pass_text or None,
    }
    if tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in tool_calls.values()
        ]

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
        assistant_msg,
    ]

    for tc in tool_calls.values():
        fn_name = tc["function"]["name"]
        fn_args_str = tc["function"]["arguments"]
        tc_id = tc["id"]

        if fn_name != "code_executor":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": f"未知工具: {fn_name}",
                }
            )
            continue

        try:
            args = json.loads(fn_args_str) if fn_args_str else {}
            if not isinstance(args, dict):
                args = {}
            result = await _code_executor_fn.ainvoke(args)
        except Exception as e:
            logger.warning(
                "tool execution failed", tool_call_id=tc_id, error=str(e), exc_info=True
            )
            result = f"工具执行失败: {e}"
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": str(result),
            }
        )

    stream2 = await openai.chat.completions.create(
        **base_kwargs,
        messages=messages,
    )
    task.model_call_count += 1
    async for event in stream2:
        if not event.choices:
            if hasattr(event, "usage") and event.usage:
                task.add_token_usage(
                    event.usage.prompt_tokens or 0,
                    event.usage.completion_tokens or 0,
                )
            continue
        delta = event.choices[0].delta
        if delta.content:
            block_reason = check_chunk_safety(delta.content)
            safe = _SAFETY_PLACEHOLDER if block_reason else delta.content
            yield emit_fn(SSEEventType.TEXT, safe)
        if hasattr(event, "usage") and event.usage:
            task.add_token_usage(
                event.usage.prompt_tokens or 0,
                event.usage.completion_tokens or 0,
            )
