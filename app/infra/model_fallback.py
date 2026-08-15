"""
模型回退管理器 — 当一个模型免费额度耗尽时自动切换到下一个模型。

回退链（按优先级）：
  qwen-max → qwen3.6-plus → deepseek-r1-distill-qwen-7b

Usage:
    from app.common.llm_client import get_chat_client
    fallback = ModelFallbackManager(client=get_chat_client())
    resp = await fallback.chat_completion(model=None, messages=[...])
"""

from __future__ import annotations

from typing import Any

import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger(__name__)

# ── 模型回退链（按优先级排序）─────────────────────────────────────────────
FALLBACK_CHAIN = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
]


class ModelFallbackManager:
    """带自动回退的 LLM 调用包装器"""

    def __init__(
        self,
        client: AsyncOpenAI,
        chain: list[str] | None = None,
    ) -> None:
        self._client = client
        # 使用传入的 chain，或从 settings 读取当前模型 + 硬编码回退
        if chain is None:
            from app.config import get_settings

            current = get_settings().llm.model
            self._chain = [current] + [m for m in FALLBACK_CHAIN if m != current]
        else:
            self._chain = chain
        self._current_index = 0
        self._switched = False
        logger.info(
            "模型回退管理器初始化", chain=self._chain, current=self._chain[self._current_index]
        )

    def _switch_to_next(self) -> str | None:
        """切换到下一个可用模型"""
        if not (self._current_index < len(self._chain) - 1):
            logger.warning("所有模型已耗尽，无可用回退")
            return None
        old = self._chain[self._current_index]
        self._current_index += 1
        new = self._chain[self._current_index]
        self._switched = True
        logger.info("模型回退切换", from_model=old, to_model=new)
        return new

    async def chat_completion(
        self,
        messages: Any,
        model: str | None = None,
        max_retries_per_model: int = 2,
        **kwargs: Any,
    ) -> object:
        """带模型回退的 LLM 调用

        返回 OpenAI chat.completions.create() 响应的 choices[0]
        所有模型耗尽时抛出 RuntimeError
        """
        model = model or self._chain[self._current_index]

        for _ in range(len(self._chain) - self._current_index):
            current_model = self._chain[self._current_index]
            for retry in range(max_retries_per_model):
                try:
                    # DeepSeek 思考模式会消耗 max_tokens 导致 content 为空
                    body = kwargs.pop("extra_body", {})
                    if "thinking" not in body:
                        body["thinking"] = {"type": "disabled"}
                    resp = await self._client.chat.completions.create(
                        model=current_model,
                        messages=messages,
                        extra_body=body,
                        **kwargs,
                    )
                    return resp
                except Exception as e:
                    error_str = str(e)
                    # 免费额度耗尽 → 切换模型
                    if (
                        "AllocationQuota.FreeTierOnly" in error_str
                        or "free tier" in error_str.lower()
                    ):
                        logger.warning("模型免费额度耗尽，切换模型", model=current_model)
                        self._switch_to_next()
                        break  # 跳出 retry 循环，进入下一个模型
                    # 限流 → 重试
                    if "429" in error_str and retry < max_retries_per_model - 1:
                        import asyncio

                        wait = 2 ** (retry + 1) * 2
                        logger.warning(
                            "LLM 限流，重试中",
                            model=current_model,
                            attempt=retry + 1,
                            wait=f"{wait}s",
                        )
                        await asyncio.sleep(wait)
                        continue
                    # 其他错误直接抛出
                    raise

        raise RuntimeError("所有模型已耗尽，无法完成调用")
