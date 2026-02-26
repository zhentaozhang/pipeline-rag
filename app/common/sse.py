"""SSE 事件类型与格式化函数。零外部依赖。"""

import json
from datetime import UTC, datetime
from typing import Any


class SSEEventType:
    THINKING = "thinking"
    TEXT = "text"
    MESSAGE = "text"
    REFERENCE = "reference"
    RECOMMENDATION = "recommend"
    ERROR = "error"
    STATUS = "status"
    DONE = "done"

    # ── 回答质量审核 ─────────────────────────────────────────────────
    REVIEW = "review"
    REVIEW_RESULT = "review_result"


def sse_event(
    event_type: str,
    content: Any = None,
    conversation_id: str | None = None,
    exchange_id: int | None = None,
    _now: datetime | None = None,
) -> str:
    """格式化单条 SSE 消息"""
    now = _now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "type": event_type,
        "content": content,
        "timestamp": now.isoformat().replace("+00:00", "Z"),
    }

    if isinstance(content, list) and event_type in (
        SSEEventType.REFERENCE,
        SSEEventType.RECOMMENDATION,
    ):
        payload["count"] = len(content)

    if conversation_id is not None and conversation_id.strip():
        payload["conversationId"] = conversation_id
    if exchange_id is not None and exchange_id > 0:
        payload["exchangeId"] = exchange_id
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
