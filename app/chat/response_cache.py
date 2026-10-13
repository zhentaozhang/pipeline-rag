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

import contextlib
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
    """会话是否有历史上下文。

    注意（019 审查发现）：摘要为空 ≠ 无历史——压缩异步触发/未到窗口时
    摘要为空但已有问答轮。缓存只能用于「首轮无上下文」的确定性问答，
    因此以「是否存在任何历史 exchange」为准（比摘要更保守、更正确）。
    """
    from sqlalchemy import select

    from app.db.models.conversation import ConversationExchange

    result = await db.execute(
        select(ConversationExchange.id)
        .where(ConversationExchange.conversation_id == conversation_id)
        .limit(1)
    )
    return result.first() is not None


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
        ttl_seconds = settings.ttl_hours * 3600
        redis = get_redis()
        await redis.set(key, payload, ex=ttl_seconds)

        # 维护文档到缓存键的反向映射索引（用于文档变更时精准主动失效）
        if doc_ids:
            for doc_id in doc_ids:
                if doc_id:
                    doc_key = f"{_KEY_PREFIX}:doc_keys:{doc_id}"
                    await redis.sadd(doc_key, key)
                    await redis.expire(doc_key, ttl_seconds)
        else:
            all_key = f"{_KEY_PREFIX}:doc_keys:__all__"
            await redis.sadd(all_key, key)
            await redis.expire(all_key, ttl_seconds)

        logger.info("chat response cache stored", key=key, events=len(events), doc_ids=doc_ids)
    except Exception:
        logger.warning("chat response cache store failed", exc_info=True)


async def invalidate_cache(doc_id: str | None = None) -> int:
    """主动失效响应缓存。

    若指定 doc_id，失效包含该文档的缓存及全局缓存；
    若 doc_id 为 None，全量清空所有响应缓存。
    """
    try:
        redis = get_redis()
        deleted = 0
        if doc_id:
            keys_to_del = set()
            # 1. 该文档对应的缓存键
            doc_key = f"{_KEY_PREFIX}:doc_keys:{doc_id}"
            keys = await redis.smembers(doc_key)
            if keys:
                keys_to_del.update(k if isinstance(k, str) else k.decode("utf-8") for k in keys)

            # 2. 全库检索的未指定文档缓存键（文档改动可能影响全局搜索结果）
            all_key = f"{_KEY_PREFIX}:doc_keys:__all__"
            all_keys = await redis.smembers(all_key)
            if all_keys:
                keys_to_del.update(k if isinstance(k, str) else k.decode("utf-8") for k in all_keys)

            if keys_to_del:
                await redis.delete(*keys_to_del)
                deleted = len(keys_to_del)

            # 清理反向映射 set
            await redis.delete(doc_key, all_key)
        else:
            # 全量模糊匹配清除
            keys_to_del = []
            async for k in redis.scan_iter(f"{_KEY_PREFIX}:*"):
                keys_to_del.append(k)
            if keys_to_del:
                chunk_size = 500
                for i in range(0, len(keys_to_del), chunk_size):
                    await redis.delete(*keys_to_del[i : i + chunk_size])
                deleted = len(keys_to_del)

        with contextlib.suppress(Exception):
            from app.rag.parent_block import clear_parent_block_cache

            clear_parent_block_cache()

        logger.info("chat response cache invalidated", doc_id=doc_id, count=deleted)
        return deleted
    except Exception:
        logger.warning("chat response cache invalidation failed", doc_id=doc_id, exc_info=True)
        return 0
