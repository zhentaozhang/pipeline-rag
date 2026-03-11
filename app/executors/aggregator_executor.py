"""
多 Worker 结果合并器
"""

from collections.abc import AsyncIterator

import structlog
from openai import AsyncOpenAI

from app.chat.schema import AggregationStyle, WorkerResult
from app.common.jinja import jinja_env as _jinja_env
from app.common.llm_client import get_chat_client, llm_breaker
from app.common.sse import SSEEventType, sse_event
from app.config import get_settings as _get_settings
from app.executors._labels import mode_label

logger = structlog.get_logger(__name__)


def _render_synthesis_prompt(question: str, results: list[WorkerResult]) -> str:
    template = _jinja_env.get_template("aggregate_synthesis.j2")
    rendered = template.render(
        question=question,
        results=[
            {
                "mode_label": r.mode.value if r.mode else "unknown",
                "text": r.text,
            }
            for r in results
        ],
    )
    return rendered


def _merge_references(results: list[WorkerResult]) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for r in results:
        for ref in r.references:
            d = ref.model_dump() if hasattr(ref, "model_dump") else ref
            key = d.get("id", "") or d.get("referenceId", "") or d.get("title", "") or str(d)
            if key and key not in seen:
                seen.add(key)
                merged.append(d)
    return merged


class AggregatorExecutor:
    """合并多 Worker 结果，输出综合回答"""

    def __init__(self) -> None:
        self._openai: AsyncOpenAI | None = None
        self._last_refs: list[dict] = []

    def _get_client(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = get_chat_client()
        return self._openai

    async def _synthesize(
        self,
        results: list[WorkerResult],
        question: str,
    ) -> tuple[str, list[dict]]:
        valid = [r for r in results if r.text.strip() and not r.error]
        if not valid:
            fallback = next((r for r in results if r.error), None)
            msg = (
                f"所有 Worker 执行失败：{fallback.error}"
                if fallback
                else "没有有效的 Worker 结果。"
            )
            return msg, _merge_references(results)

        prompt = _render_synthesis_prompt(question, valid)
        try:
            s = _get_settings()
            async with llm_breaker():
                resp = await self._get_client().chat.completions.create(
                    model=s.llm.model,
                    messages=[
                        {"role": "system", "content": "你是一个专业的多源信息综合助手。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=2048,
                    timeout=s.llm.timeout_seconds,
                )
            merged_text = resp.choices[0].message.content or ""
        except Exception:
            logger.exception("synthesis_failed")
            merged_text = self._concatenate(valid)[0]

        merged_refs = _merge_references(results)
        return merged_text, merged_refs

    async def synthesize_streaming(
        self,
        results: list[WorkerResult],
        question: str,
        style: str = AggregationStyle.SYNTHESIZE,
        conversation_id: str | None = None,
        exchange_id: int | None = None,
    ) -> AsyncIterator[str]:
        """流式综合多源回答，逐 token 输出 SSE text 事件。

        完成后可通过 ``last_refs`` 属性获取合并后的引用列表。
        """
        self._last_refs = []

        if not results:
            yield sse_event(
                SSEEventType.TEXT,
                "没有可用的信息来源。",
                conversation_id=conversation_id,
                exchange_id=exchange_id,
            )
            return

        if style == AggregationStyle.CONCATENATE:
            merged_text, merged_refs = self._concatenate(results)
            yield sse_event(
                SSEEventType.TEXT,
                merged_text,
                conversation_id=conversation_id,
                exchange_id=exchange_id,
            )
            self._last_refs = merged_refs
            return

        valid = [r for r in results if r.text.strip() and not r.error]
        if not valid:
            fallback = next((r for r in results if r.error), None)
            msg = (
                f"所有 Worker 执行失败：{fallback.error}"
                if fallback
                else "没有有效的 Worker 结果。"
            )
            yield sse_event(
                SSEEventType.TEXT,
                msg,
                conversation_id=conversation_id,
                exchange_id=exchange_id,
            )
            self._last_refs = _merge_references(results)
            return

        prompt = _render_synthesis_prompt(question, valid)
        s = _get_settings()
        try:
            stream = await self._get_client().chat.completions.create(
                model=s.llm.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的多源信息综合助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2048,
                timeout=s.llm.timeout_seconds,
                stream=True,
            )
            async for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                if delta.content:
                    yield sse_event(
                        SSEEventType.TEXT,
                        delta.content,
                        conversation_id=conversation_id,
                        exchange_id=exchange_id,
                    )
        except Exception:
            logger.exception("synthesis_streaming_failed")
            merged_text, _ = self._concatenate(valid)
            yield sse_event(
                SSEEventType.TEXT,
                merged_text,
                conversation_id=conversation_id,
                exchange_id=exchange_id,
            )

        self._last_refs = _merge_references(results)

    @property
    def last_refs(self) -> list[dict]:
        return self._last_refs

    @staticmethod
    def _concatenate(results: list[WorkerResult]) -> tuple[str, list[dict]]:
        parts: list[str] = []
        for r in results:
            label = mode_label(r.mode) if r.mode else ""
            if r.text.strip():
                parts.append(f"【{label}】\n{r.text}")
        return "\n\n".join(parts), _merge_references(results)
