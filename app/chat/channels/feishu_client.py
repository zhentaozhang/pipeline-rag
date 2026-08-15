"""飞书机器人渠道（P3-4）

长连接事件订阅（lark-oapi WSClient，无需公网回调）→ 解析 im.message.receive_v1
→ (chat_id, open_id) ↔ conversation_id 会话映射 → 复用 BusinessChatService.stream
→ SSE 事件流转为飞书 interactive 卡片流式更新（节流）。

启用：FEISHU_ENABLED=true + FEISHU_APP_ID/FEISHU_APP_SECRET（飞书自建应用凭证）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

# 飞书 SDK 依赖懒加载：未启用渠道时不应引入（SDK 体积较大）
_lark_client: Any | None = None
_lark_lock = threading.Lock()


def _get_lark() -> Any:
    """懒加载 lark-oapi 同步客户端（消息发送/更新）"""
    global _lark_client
    if _lark_client is not None:
        return _lark_client
    with _lark_lock:
        if _lark_client is not None:
            return _lark_client
        import lark_oapi as lark

        settings = get_settings().feishu
        _lark_client = (
            lark.Client.builder()
            .app_id(settings.app_id)
            .app_secret(settings.app_secret)
            .log_level(lark.LogLevel.WARN)
            .build()
        )
        return _lark_client


def build_card(content: str) -> str:
    """interactive 卡片 JSON（lark_md 正文）"""
    return json.dumps(
        {
            "config": {"wide_screen_mode": True},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
        },
        ensure_ascii=False,
    )


def send_card(chat_id: str, content: str) -> str:
    """发送初始卡片，返回 message_id"""
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(build_card(content))
            .build()
        )
        .build()
    )
    resp = _get_lark().im.v1.message.create(req)
    if not resp.success():
        logger.warning("feishu send failed", chat_id=chat_id, code=resp.code, msg=resp.msg)
        raise RuntimeError(f"feishu send failed: {resp.code} {resp.msg}")
    message_id = resp.data.message_id
    return str(message_id)


def update_card(message_id: str, content: str) -> None:
    """更新已发送卡片（流式回复）"""
    from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody

    req = (
        UpdateMessageRequest.builder()
        .message_id(message_id)
        .body(
            UpdateMessageRequestBody.builder()
            .msg_type("interactive")
            .content(build_card(content))
            .build()
        )
        .build()
    )
    resp = _get_lark().im.v1.message.update(req)
    if not resp.success():
        # 更新失败不影响主流程（下一轮会再尝试）
        logger.warning(
            "feishu update failed", message_id=message_id, code=resp.code, msg=resp.msg
        )


# ── 长连接网关 ───────────────────────────────────────────────────────────────


class FeishuGateway:
    """长连接事件网关：启动 ws 客户端 + 事件分发"""

    def __init__(self) -> None:
        self._ws_client: Any | None = None
        self._thread: threading.Thread | None = None
        self._handler: Callable[[Any], Awaitable[None]] | None = None

    def set_handler(self, handler: Callable[[Any], Any]) -> None:
        self._handler = handler

    def start(self) -> None:
        """启动长连接（阻塞，放入后台线程）"""
        from lark_oapi import EventDispatcherHandler

        settings = get_settings().feishu
        dispatcher = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_event)
            .build()
        )

        from lark_oapi.ws import Client as WSClient

        self._ws_client = WSClient(
            settings.app_id,
            settings.app_secret,
            event_handler=dispatcher,
            log_level=2,  # WARN
        )
        self._thread = threading.Thread(target=self._ws_client.start, name="feishu-ws", daemon=True)
        self._thread.start()
        logger.info("feishu gateway started", app_id=settings.app_id)

    def stop(self) -> None:
        if self._ws_client is not None:
            try:
                self._ws_client.stop()
            except Exception:
                logger.warning("feishu ws stop failed", exc_info=True)
            self._ws_client = None
        logger.info("feishu gateway stopped")

    def _on_event(self, data: Any) -> None:
        """lark-oapi 事件回调（同步签名，内部转异步任务）"""
        handler = self._handler
        if handler is None:
            return
        # 事件处理放到独立线程任务中（lark 回调线程不应阻塞）
        threading.Thread(
            target=self._run_handler, args=(handler, data), name="feishu-msg", daemon=True
        ).start()

    @staticmethod
    def _run_handler(handler: Callable[[Any], Any], data: Any) -> None:
        try:
            asyncio.run(handler(data))
        except Exception:
            logger.exception("feishu event handler failed")


# ── 模块级单例 ───────────────────────────────────────────────────────────────

_gateway: FeishuGateway | None = None


def get_gateway() -> FeishuGateway:
    global _gateway
    if _gateway is None:
        _gateway = FeishuGateway()
    return _gateway
