"""飞书事件处理：消息解析、@过滤、会话映射、流式回复（P3-4）"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.sse import SSEEventType
from app.config import get_settings

logger = structlog.get_logger(__name__)

_MENTION_HINT = "（群聊中请 @ 机器人后提问）"


def parse_text_content(content: str | None) -> str:
    """text 消息 content 是 JSON 字符串：{"text":"..."}"""
    if not content:
        return ""
    try:
        payload = json.loads(content)
        return str(payload.get("text", "")).strip()
    except (ValueError, AttributeError):
        return content.strip()


async def resolve_conversation_id(
    db: AsyncSession, chat_id: str, open_id: str
) -> tuple[str, bool]:
    """(chat_id, open_id) ↔ conversation_id 映射；不存在则新建。返回 (conversation_id, created)"""
    from app.db.models.conversation import FeishuBinding
    from app.infra.id_generator import next_id

    stmt = select(FeishuBinding).where(
        FeishuBinding.chat_id == chat_id, FeishuBinding.open_id == open_id
    )
    binding = (await db.execute(stmt)).scalar_one_or_none()
    if binding is not None:
        return binding.conversation_id, False

    conversation_id = str(next_id())
    db.add(
        FeishuBinding(
            chat_id=chat_id,
            open_id=open_id,
            conversation_id=conversation_id,
        )
    )
    await db.commit()
    logger.info("feishu binding created", chat_id=chat_id, conversation_id=conversation_id)
    return conversation_id, True


async def handle_message_event(data: Any) -> None:
    """im.message.receive_v1 事件主处理"""
    from app.config import get_settings

    event = getattr(data, "event", None)
    message = getattr(event, "message", None)
    sender = getattr(event, "sender", None)
    if message is None or sender is None:
        return

    # ── 群聊 @ 过滤：p2p 直接响应；群聊需要 mentions（@ 了机器人）──
    chat_type = message.chat_type or ""
    if chat_type != "p2p":
        mentions = getattr(message, "mentions", None) or []
        if not mentions:
            logger.info("feishu group msg ignored (no mention)", chat_id=message.chat_id)
            return
        settings = get_settings().feishu
        if settings.bot_open_id:
            mentioned_bot = any(
                getattr(m, "id", None) and getattr(m.id, "open_id", None) == settings.bot_open_id
                for m in mentions
            )
            if not mentioned_bot:
                logger.info("feishu group msg ignored (bot not mentioned)")
                return

    if (message.message_type or "") != "text":
        await _reply_text_only(
            message.chat_id,
            "目前只支持文本消息。",
        )
        return

    question = parse_text_content(message.content)
    if not question:
        await _reply_text_only(message.chat_id, "请问有什么可以帮您？")
        return

    sender_id = getattr(sender, "sender_id", None)
    open_id = getattr(sender_id, "open_id", None) or ""
    await _answer_question(message.chat_id, open_id, question)


async def _answer_question(chat_id: str, open_id: str, question: str) -> None:
    """会话映射 + 复用 BusinessChatService.stream + 卡片流式回复"""
    from app.chat.channels.feishu_client import send_card, update_card
    from app.chat.service import BusinessChatService
    from app.db.session import _session_factory

    assert _session_factory is not None
    async with _session_factory() as db:
        conversation_id, _ = await resolve_conversation_id(db, chat_id, open_id)

        # 发送"思考中"初始卡片
        message_id = send_card(chat_id, "🤔 正在思考...")

        service = BusinessChatService(db)
        req = _build_request(conversation_id, question, open_id)
        chunks: list[str] = []
        last_content = ""
        last_send_at = 0.0
        interval_s = get_settings().feishu.stream_update_interval_ms / 1000.0
        exchange_id: str | None = None

        try:
            async for raw in service.stream(req):
                event = _parse_sse(raw)
                if event is None:
                    continue
                etype = event.get("type", "")
                content = event.get("content") or ""
                if etype == SSEEventType.THINKING:
                    chunks.append(f"💭 {content}")
                elif etype == SSEEventType.TEXT and content:
                    chunks.append(content)
                elif etype == SSEEventType.DONE:
                    exchange_id = event.get("exchangeId")
                    break
                elif etype == SSEEventType.ERROR:
                    chunks.append(f"⚠️ {content}")
                    break

                # 节流：内容变化且超过间隔才更新卡片
                now = time.monotonic()
                body = "".join(chunks)
                if body != last_content and now - last_send_at >= interval_s:
                    update_card(message_id, body[-1800:])  # 卡片正文长度上限保护
                    last_content = body
                    last_send_at = now

            final_body = "".join(chunks)
            if exchange_id:
                final_body += _reference_footer(conversation_id, exchange_id)
            update_card(message_id, final_body or "（无回答内容）")
        except Exception as e:
            logger.exception("feishu answer failed", chat_id=chat_id)
            from contextlib import suppress

            with suppress(Exception):
                update_card(message_id, f"⚠️ 服务异常：{e}")


def _build_request(conversation_id: str, question: str, open_id: str) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        question=question,
        conversation_id=conversation_id,
        chat_mode="auto",
        doc_ids=[],
        selected_document_id=None,
        user_key=open_id or None,  # 渠道身份 → 用户级事实记忆维度
    )


def _reference_footer(conversation_id: str, exchange_id: str) -> str:
    """引用溯源入口：跳转平台 Web 查看（P1-1 引用功能已就绪）"""
    base = get_settings().feishu.web_base_url or "http://localhost:5173"
    url = f"{base.rstrip('/')}/chat/{conversation_id}?exchange={exchange_id}"
    return f"\n\n📎 [查看回答来源与引用]({url})"


def _parse_sse(raw: str) -> dict[str, Any] | None:
    """解析 SSE 行 `data: {...}`"""
    line = raw.strip()
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


async def _reply_text_only(chat_id: str, text: str) -> None:
    """简单文本回复（不支持的类型/空消息提示）"""
    from app.chat.channels.feishu_client import send_card

    try:
        send_card(chat_id, text)
    except Exception:
        logger.warning("feishu text-only reply failed", chat_id=chat_id, exc_info=True)
