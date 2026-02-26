from __future__ import annotations

import asyncio
import uuid as uuid_mod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.common.enums import ChatQueryMode

from app.common.exceptions import BaseCode, PipelineRAGBaseException

logger = structlog.get_logger(__name__)


_CHINESE_WEEKDAY = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}


def _estimate_tokens(text: str) -> int:
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f' or '\uff00' <= c <= '\uffef')
    ascii = sum(1 for c in text if c.isascii() and c.isprintable())
    other = len(text) - cjk - ascii
    return int(cjk / 1.5 + ascii / 4 + other / 2)


def _format_current_date(d: datetime) -> str:
    return f"{d.strftime('%Y-%m-%d')}（{_CHINESE_WEEKDAY[d.weekday()]}）"


def _normalize_question(question: str | None) -> str:
    if question is None or not question.strip():
        raise PipelineRAGBaseException(BaseCode.BAD_REQUEST, "question 不能为空")
    return question.strip()


def _normalize_conversation_id(conversation_id: str | None) -> str:
    if conversation_id and conversation_id.strip():
        return conversation_id.strip()
    return uuid_mod.uuid4().hex


def _build_error_message(error: BaseException) -> str:
    current: BaseException | None = error
    while current is not None:
        if hasattr(current, "status_code") and hasattr(current, "response_body"):
            body = getattr(current, "response_body", None) or ""
            if body.strip():
                return f"{getattr(current, 'status_code', '')} from {getattr(current, 'request_method', '')} {getattr(current, 'request_url', '')} | responseBody={body}"
            return str(current)
        current = current.__cause__
    return str(error) if str(error) else type(error).__name__


def _parse_required_chat_mode(value: str | None) -> ChatQueryMode:
    from app.common.enums import normalize_chat_mode

    if not value or not value.strip() or value.strip().upper() == "ALL":
        raise PipelineRAGBaseException(BaseCode.BAD_REQUEST, "chatMode 不能为空")
    try:
        return normalize_chat_mode(value)
    except ValueError:
        raise PipelineRAGBaseException(BaseCode.BAD_REQUEST, f"chatMode 非法: {value}") from None


async def _async_generator_with_timeout(
    gen: AsyncIterator[str], timeout: int
) -> AsyncIterator[str]:
    try:
        while True:
            yield await asyncio.wait_for(anext(gen), timeout=timeout)
    except StopAsyncIteration:
        return
    except TimeoutError:
        logger.warning("generator chunk timed out, stopping stream gracefully")
        return
