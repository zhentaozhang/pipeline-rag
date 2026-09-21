"""LangChain/LangGraph 回调 → 自研 Tracer generation

不复用 langfuse 的 `langchain.CallbackHandler`（它走 langfuse 自身的
`get_client()`，与本项目单例是两套客户端，且 langfuse 只读 os.environ 而
本项目配置来自 .env，会丢失配置）。本实现仅依赖已安装的 langchain_core，
把每次 LLM 调用映射到 `tracer.record_generation`，与流式路径共用同一
tracer/client 与 usage/cost 口径。
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler


class TracerCallbackHandler(AsyncCallbackHandler):
    """把 LangGraph/LangChain 的 chat model 调用记录为 Langfuse generation。"""

    def __init__(self, tracer: Any, name_prefix: str = "agent") -> None:
        super().__init__()
        self._tracer = tracer
        self._name_prefix = name_prefix
        self._pending: dict[str, dict[str, Any]] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        kwargs_serialized = (serialized or {}).get("kwargs", {}) or {}
        model = kwargs_serialized.get("model_name") or kwargs_serialized.get("model")
        try:
            first_batch = messages[0] if messages else []
            input_text = "\n".join(
                str(getattr(m, "content", m)) for m in first_batch
            )
        except Exception:
            input_text = str(messages)
        self._pending[str(run_id)] = {"model": model, "input": input_text}

    async def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        info = self._pending.pop(str(run_id), {})

        output_text = ""
        try:
            batch = response.generations[0] if response.generations else []
            if batch:
                gen = batch[0]
                output_text = getattr(gen, "text", "") or str(
                    getattr(getattr(gen, "message", None), "content", "") or ""
                )
        except Exception:
            output_text = ""

        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        model = info.get("model") or llm_output.get("model_name") or "unknown"

        from app.observability.llm_observe import record_generation

        record_generation(
            self._tracer,
            f"{self._name_prefix}_llm",
            model=model,
            input=info.get("input"),
            output=output_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
