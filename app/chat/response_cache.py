"""对话响应缓存（第二轮架构评审·可以优化 3）

场景：企业知识问答中「无历史上下文的确定性提问」重复率极高（FAQ/制度/产品
手册），每次提问都走完整 LLM 链路。本模块对这类请求缓存最终答案与引用，
命中时跳过编排/检索/生成，直接回放。

安全边界（保守设计）：
- 仅当会话无历史上下文（摘要为空）时缓存/命中——多轮上下文不会污染缓存
- 缓存键 = 规范化问题 + 模式 + 文档集（跨会话复用，不绑定会话）
- TTL 默认 24h；仅 RETRIEVAL 类确定性问答（通过 chat_mode 判断）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import get_settings
from app.infra.redis_lease import get_redis

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "pipeline_rag:chat:cache"
_CACHEABLE_MODES = {"auto", "retrieval"}


@dataclass
class CacheHit:
    events: list[str] = field(default_factory=list)  # 原始 SSE 行（含 done）
    answer: str = ""


def _normalize_question(question: str) -> str:
    # 去全部空白 + 小写：语义相同的不同空格写法命中同一缓存键
    return "".join(question.lower().split())


def build_cache_key(question: str, chat_mode: str, doc_ids: list[str]) -> str:
    """缓存键：规范化问题 + 模式 + 文档集（跨会话复用）"""
    raw = f"{_normalize_question(question)}|{chat_mode}|{','.join(sorted(doc_ids))}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}:{digest}"


def is_cacheable(chat_mode: str, has_history: bool) -> bool:
    """仅确定性问答且无历史上下文时可缓存"""
    return chat_mode in _CACHEABLE_MODES and not has_history


async def has_history(db: Any, conversation_id: str) -> bool:
    """会话是否有历史上下文（摘要非空即视为有历史）"""
    from app.chat.memory_service import PersistentConversationMemoryService

    memory_service = PersistentConversationMemoryService(db)
    summary = await memory_service.get_summary(conversation_id)
    return bool(summary and summary.strip())


async def lookup(db: Any, conversation_id: str, question: str, chat_mode: str, doc_ids: list[str]) -> CacheHit | None:
    """缓存查询：命中返回可回放事件；否则 None。Redis 异常静默降级（不阻断）"""
    if not is_cacheable(chat_mode, await has_history(db, conversation_id)):
        return None
    try:
        key = build_cache_key(question, chat_mode, doc_ids)
        raw = await get_redis().get(key)
        if not raw:
            return None
        payload = json.loads(str(raw))
        events = payload.get("events") or []
        answer = payload.get("answer") or ""
        if not events:
            return None
        logger.info("chat response cache hit", key=key, events=len(events))
        return CacheHit(events=events, answer=answer)
    except Exception:
        logger.warning("chat response cache lookup failed", exc_info=True)
        return None


async def store(
    db: Any,
    conversation_id: str,
    question: str,
    chat_mode: str,
    doc_ids: list[str],
    events: list[str],
    answer: str,
) -> None:
    """写入缓存（仅确定性问答 + 无历史 + 非失败/停止轮）"""
    try:
        if not is_cacheable(chat_mode, await has_history(db, conversation_id)):
            return
        settings = get_settings().chat_cache
        key = build_cache_key(question, chat_mode, doc_ids)
        payload = json.dumps({"events": events, "answer": answer}, ensure_ascii=False)
        await get_redis().set(key, payload, ex=settings.ttl_hours * 3600)
        logger.info("chat response cache stored", key=key, events=len(events))
    except Exception:
        logger.warning("chat response cache store failed", exc_info=True)
