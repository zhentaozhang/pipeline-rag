"""
运行时任务状态 + 进程级任务注册表

功能：
- ChatTaskInfo: 单次对话的运行时状态（取消标记、token 计数、状态机等）
- ChatRuntimeRegistry: 进程内任务注册，防止同进程重入（配合 Redis 锁双重保护）
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.chat.schema import ExecutionPlan
from app.chat.state_machine import ConversationState, ConversationStateMachine
from app.chat.support import StreamEventMetadata
from app.observability.metrics import LLM_TOKEN_TOTAL
from app.observability.trace_models import ChatDebugTrace


class ChatTaskInfo(BaseModel):
    """
    单次对话任务的上下文信息
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

    conversation_id: str
    question: str
    start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    plan: ExecutionPlan | None = None

    # ── 核心辨识字段 ────────────────────────────────────────────────────
    exchange_id: int | None = None
    chat_mode: str | None = None
    trace_id: str | None = None

    # ── 文档选择 ────────────────────────────────────────────────────────
    selected_document_id: str | None = None
    selected_document_name: str | None = None
    selected_task_id: str | None = None

    # ── 租赁锁 ──────────────────────────────────────────────────────────
    lease_key: str | None = None
    lease_token: str | None = None

    # ── 事件元数据 ───────────────────────────────────────────────────────
    event_metadata: StreamEventMetadata | None = None

    # ── SSE 观测上下文 ────────────────────────────────────────────────────
    sink: Any | None = None
    thinking_steps: list[str] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)

    # ── 调试追踪 ────────────────────────────────────────────────────────
    debug_trace: ChatDebugTrace | None = None

    # ── 日期 ────────────────────────────────────────────────────────────
    current_date: str = ""
    current_date_text: str = ""

    # ── 运行时缓冲 ──────────────────────────────────────────────────────
    answer_buffer: list[str] = Field(default_factory=list)

    # ── 性能指标 ────────────────────────────────────────────────────────
    _first_response_time_ms: int = 0

    # ── 终态保护 ────────────────────────────────────────────────────────
    finalized: bool = False

    # ── 流量控制 ────────────────────────────────────────────────────────
    cancelled: bool = False
    tokens_used: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0

    # ── Token 用量（原 ModelUsageTracker，已内联至此） ──────────────────
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_name: str = "unknown"

    # ── 运行时依赖（exclude → 不参与序列化） ────────────────────────────
    tracer: Any | None = Field(default=None, exclude=True)
    _cancel_event: asyncio.Event | None = None
    _state_machine: ConversationStateMachine | None = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._cancel_event = asyncio.Event()
        self._lock = threading.Lock()
        self._state_machine = ConversationStateMachine()

    @property
    def sm(self) -> ConversationStateMachine:
        if self._state_machine is None:
            self._state_machine = ConversationStateMachine()
        return self._state_machine

    @property
    def conv_state(self) -> ConversationState:
        return self.sm.state

    def finalize(self) -> bool:
        """带锁确保只执行一次终结（CAS 语义）"""
        with self._lock:
            if self.finalized:
                return False
            self.finalized = True
            return True

    def add_token_usage(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        LLM_TOKEN_TOTAL.labels(model=self.model_name, token_type="prompt").inc(prompt)
        LLM_TOKEN_TOTAL.labels(model=self.model_name, token_type="completion").inc(completion)

    @property
    def first_response_time_ms(self) -> int:
        return self._first_response_time_ms

    def try_set_first_response_time(self, elapsed_ms: int) -> bool:
        """CAS：仅当首字响应时间尚未设置时写入。返回 True 表示本次调用成功设置。"""
        with self._lock:
            if self._first_response_time_ms == 0:
                self._first_response_time_ms = elapsed_ms
                return True
            return False

    def cancel(self) -> None:
        """触发取消"""
        self.cancelled = True
        if self._cancel_event:
            self._cancel_event.set()

    @property
    def cancel_event(self) -> asyncio.Event:
        if not self._cancel_event:
            self._cancel_event = asyncio.Event()
        return self._cancel_event


class ChatRuntimeRegistry:
    """
    进程内任务注册表（内存级，进程重启后清空）。
    Redis 锁是集群级保护，本注册表是进程内二次防护。
    """

    _registry: dict[str, ChatTaskInfo] = {}

    @classmethod
    def register(cls, task: ChatTaskInfo) -> bool:
        if task.conversation_id in cls._registry:
            return False
        cls._registry[task.conversation_id] = task
        return True

    @classmethod
    def unregister(cls, conversation_id: str, task: ChatTaskInfo | None = None) -> None:
        if task is not None:
            existing = cls._registry.get(conversation_id)
            if existing is not task:
                return
        cls._registry.pop(conversation_id, None)

    @classmethod
    def get(cls, conversation_id: str) -> ChatTaskInfo | None:
        return cls._registry.get(conversation_id)

    @classmethod
    def replace(cls, task: ChatTaskInfo) -> bool:
        old = cls._registry.get(task.conversation_id)
        if old is not None:
            old.cancel()
        cls._registry[task.conversation_id] = task
        return True

    @classmethod
    def cancel(cls, conversation_id: str) -> bool:
        """
        发送取消信号（供 /api/chat/stop 调用）。
        返回 True 表示找到并取消，False 表示未找到活跃任务。
        """
        task = cls._registry.get(conversation_id)
        if task:
            task.cancel()
            return True
        return False

    @classmethod
    def is_running(cls, conversation_id: str) -> bool:
        return conversation_id in cls._registry

    @classmethod
    def active_count(cls) -> int:
        return len([v for v in cls._registry.values() if v is not None])
