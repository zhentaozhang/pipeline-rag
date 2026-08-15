from __future__ import annotations

import structlog

from app.common.enums import ChatQueryMode
from app.common.enums import normalize_chat_mode as _normalize_chat_mode
from app.common.text_utils import safe_text
from app.config import get_settings

logger = structlog.get_logger(__name__)

_CAPABILITY_HINTS = {
    "你都能干什么",
    "你能做什么",
    "你可以做什么",
    "你会什么",
    "你是谁",
    "怎么用你",
    "你能帮我什么",
}
_OPEN_CHAT_HINTS = {
    "天气",
    "温度",
    "下雨",
    "新闻",
    "股价",
    "汇率",
    "热搜",
    "今天",
    "明天",
    "最新",
    "现在",
}
_CHITCHAT_HINTS = {"你好", "您好", "hello", "hi", "谢谢", "感谢", "再见", "拜拜"}


def normalize_chat_mode(chat_mode: str) -> ChatQueryMode:
    """将前端传入的 chatMode 字符串规范化成枚举值"""
    try:
        return _normalize_chat_mode(chat_mode)
    except ValueError:
        # 体检 C5：静默降级可见化
        from app.observability.metrics import DEGRADATION_TOTAL

        DEGRADATION_TOTAL.labels(reason="invalid_chat_mode").inc()
        logger.warning("chat_mode degraded to AUTO_DOCUMENT", raw=chat_mode)
        return ChatQueryMode.AUTO_DOCUMENT


def looks_like_capability_question(question: str) -> bool:
    if not question:
        return False
    return any(hint in question for hint in _CAPABILITY_HINTS)


def looks_like_open_chat_question(question: str, requires_fresh_search: bool) -> bool:
    if not question:
        return False
    if requires_fresh_search:
        return True
    if any(hint in question for hint in _OPEN_CHAT_HINTS):
        return True
    return any(hint in question for hint in _CHITCHAT_HINTS)


def build_document_mode_no_evidence_reply(question: str, requires_fresh_search: bool) -> str:
    settings = get_settings()
    normalized_question = safe_text(question)
    if looks_like_capability_question(normalized_question):
        return (
            "当前你正在使用\u201c当前文档问答\u201d模式，我会优先基于所选文档回答。"
            "这个问题更像是在询问助手能力，而不是当前文档内容。"
            "如果你想了解我能做什么，请切换到\u201c开放式提问\u201d模式。"
        )
    if looks_like_open_chat_question(normalized_question, requires_fresh_search):
        return (
            "当前你正在使用\u201c当前文档问答\u201d模式，我只能基于所选文档回答。"
            "这个问题更像开放式提问，例如天气、最新信息或一般交流。"
            "如果你想继续问这类问题，请切换到\u201c开放式提问\u201d模式。"
        )
    return (
        settings.rag.no_evidence_reply
        or "当前没有从当前文档中检索到足够证据，暂时不能给出可靠结论。"
        "你可以补充更具体的标题、术语或关键词后再试。"
    )
