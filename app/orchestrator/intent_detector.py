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

# 寒暄/致谢类，与"实时信息"无关，命中即走开放问答。
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
    """问题是否应分流到开放问答（ReAct Agent + 联网检索）。

    分流依据只有两类，且都不含"时间限定词"：

    1. ``requires_fresh_search`` —— 由 ``TimeSensitiveQueryHelper`` 判定，语义是
       "该问题需要实时/联网信息"；
    2. 命中实时信息领域词（天气 / 股价 / 汇率 / 新闻 …，唯一来源
       ``TimeSensitiveQueryHelper.is_fresh_info_domain``）或寒暄词。

    注意：不要把「今天 / 明天 / 最新 / 现在」这类**时间限定词**放进分流依据。
    它们表达时间语义，与是否需要联网无关。早前它们混在领域词表里，导致
    「今天报销流程有变化吗」在 AUTO_DOCUMENT 模式下被静默改道到联网搜索，
    完全绕过知识库。
    """
    if not question:
        return False
    if requires_fresh_search:
        return True

    from app.orchestrator.time_helper import TimeSensitiveQueryHelper

    if TimeSensitiveQueryHelper.is_fresh_info_domain(question):
        return True
    return any(hint in question for hint in _CHITCHAT_HINTS)


async def jev_classify_intent(question: str) -> dict:
    """使用 JEV System 1 决策模型进行高泛化意图分类与实时性判断（弥补规则词表的盲区）"""
    from app.infra.jev_client import get_jev_client

    jev = get_jev_client()
    return await jev.system_one(
        state=question,
        questions={
            "intent": {
                "type": "choice",
                "instructions": "判断该问题的核心意图类别",
                "options": {
                    "document_qa": "可从企业知识库/内部规章文档中查到答案的业务问题",
                    "open_chat": "需要联网实时信息（天气/股价/新闻等）或日常寒暄闲聊",
                    "capability": "询问助手本身的功能、用法或身份",
                    "ambiguous": "问题信息量严重不足，无法确定具体意图",
                },
            },
            "needs_realtime": {
                "type": "noul",
                "instructions": "该问题是否必须依赖实时外部信息才能回答（天气/实时股市/最新新闻等）",
            },
        },
    )


def build_open_chat_suggestion() -> str:
    """「该问题更像开放式提问」的提示文案。

    与分流判定解耦：调整措辞不应影响路由行为，反之亦然。
    """
    return (
        "当前你正在使用\u201c当前文档问答\u201d模式，我只能基于所选文档回答。"
        "这个问题更像开放式提问，例如天气、最新信息或一般交流。"
        "如果你想继续问这类问题，请切换到\u201c开放式提问\u201d模式。"
    )


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
        return build_open_chat_suggestion()
    return (
        settings.rag.no_evidence_reply
        or "当前没有从当前文档中检索到足够证据，暂时不能给出可靠结论。"
        "你可以补充更具体的标题、术语或关键词后再试。"
    )
