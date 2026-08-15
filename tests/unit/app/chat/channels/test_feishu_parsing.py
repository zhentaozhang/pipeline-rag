"""P3-4：飞书渠道——纯函数解析与 @ 过滤逻辑"""

import json
from types import SimpleNamespace

import pytest

from app.chat.channels.feishu_client import build_card
from app.chat.channels.feishu_event_handler import (
    _parse_sse,
    handle_message_event,
    parse_text_content,
)


def test_parse_text_content_json():
    assert parse_text_content('{"text":"你好"}') == "你好"
    assert parse_text_content('{"text":" 带空格 "}') == "带空格"
    assert parse_text_content("") == ""
    assert parse_text_content(None) == ""
    # 非 JSON（容错回退原文）
    assert parse_text_content("直接文本") == "直接文本"


def test_build_card_valid_json():
    card = build_card("回答内容")
    payload = json.loads(card)
    assert payload["elements"][0]["tag"] == "div"
    assert payload["elements"][0]["text"]["content"] == "回答内容"
    # ensure_ascii=False：中文原样
    assert "回答内容" in card


def test_parse_sse_line():
    raw = 'data: {"type": "text", "content": "答案", "conversationId": "c1"}'
    event = _parse_sse(raw)
    assert event is not None
    assert event["type"] == "text"
    assert event["content"] == "答案"
    # 非 data 行忽略
    assert _parse_sse(": heartbeat") is None
    # 非法 JSON 忽略
    assert _parse_sse("data: {broken") is None


def _mention(open_id: str = "ou_bot") -> SimpleNamespace:
    return SimpleNamespace(id=SimpleNamespace(open_id=open_id), name="机器人")


def _message(chat_type: str, mentions: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        chat_id="oc_1",
        chat_type=chat_type,
        message_type="text",
        content='{"text":"问题"}',
        mentions=mentions,
    )


@pytest.mark.asyncio
async def test_group_message_without_mention_ignored(monkeypatch):
    """群聊未 @ 机器人 → 不响应（不触发任何回复）"""
    replied = []

    async def fake_reply(chat_id, text):
        replied.append(text)

    monkeypatch.setattr(
        "app.chat.channels.feishu_event_handler._reply_text_only", fake_reply
    )

    event = SimpleNamespace(
        message=_message("group", mentions=None),
        sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_user")),
    )
    data = SimpleNamespace(event=event)
    await handle_message_event(data)
    assert replied == []


@pytest.mark.asyncio
async def test_p2p_message_answered(monkeypatch):
    """私聊消息 → 进入回答链路"""
    answered = []

    async def fake_answer(chat_id, open_id, question):
        answered.append((chat_id, open_id, question))

    monkeypatch.setattr(
        "app.chat.channels.feishu_event_handler._answer_question", fake_answer
    )

    event = SimpleNamespace(
        message=_message("p2p", mentions=[]),
        sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_user")),
    )
    data = SimpleNamespace(event=event)
    await handle_message_event(data)
    assert answered == [("oc_1", "ou_user", "问题")]


@pytest.mark.asyncio
async def test_group_mention_answered_with_bot_id(monkeypatch):
    """群聊 @ 机器人（配置 bot_open_id 精确匹配）→ 响应"""
    from app.config import get_settings

    answered = []

    async def fake_answer(chat_id, open_id, question):
        answered.append(question)

    monkeypatch.setattr(
        "app.chat.channels.feishu_event_handler._answer_question", fake_answer
    )
    settings = get_settings()
    original = settings.feishu.bot_open_id
    settings.feishu.bot_open_id = "ou_bot"
    try:
        event = SimpleNamespace(
            message=_message("group", mentions=[_mention("ou_bot")]),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_user")),
        )
        await handle_message_event(SimpleNamespace(event=event))
    finally:
        settings.feishu.bot_open_id = original
    assert answered == ["问题"]


@pytest.mark.asyncio
async def test_non_text_message_prompts(monkeypatch):
    """图片等非文本消息 → 提示文案"""
    replied = []

    async def fake_reply(chat_id, text):
        replied.append(text)

    monkeypatch.setattr(
        "app.chat.channels.feishu_event_handler._reply_text_only", fake_reply
    )
    msg = _message("p2p")
    msg.message_type = "image"
    event = SimpleNamespace(
        message=msg, sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_user"))
    )
    await handle_message_event(SimpleNamespace(event=event))
    assert replied and "文本" in replied[0]
