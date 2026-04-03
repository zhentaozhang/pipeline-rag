"""Chat API VO 模型（替代端点内联 dict）"""

from pydantic import Field

from app.api.schemas.response import CamelModel


class ConversationSessionVO(CamelModel):
    """会话视图——对话列表项"""

    id: int = 0
    conversation_id: str = ""
    title: str = ""
    created_at: str | None = None
    chat_mode: str = "auto"
    exchange_count: int = 0
    memory_summary: str = ""
    running: bool = False
    checkpoint_count: int = 0
    message_count: int = 0
    latest_user_message: str = ""
    latest_assistant_message: str = ""
    latest_exchange_id: str | None = None
    latest_turn_status: str = ""
    latest_turn_error_message: str = ""
    selected_document_id: str = ""
    selected_document_name: str = ""
    updated_at: str | None = None


class SessionPageResponse(CamelModel):
    """会话列表视图—分页响应"""

    records: list[ConversationSessionVO] = Field(default_factory=list, alias="sessions")
    total: int = 0
    page_no: int = 1  # JSON → pageNo (via CamelModel to_camel)
    page_size: int = 20  # JSON → pageSize
    total_pages: int = 0  # totalPages


class ExchangeVO(CamelModel):
    id: str = ""
    conversation_id: str = ""
    question: str = ""
    answer: str = ""
    tokens_used: int | None = None
    created_at: str | None = None
    execution_mode: str = ""
    turn_status: int | None = None
    first_response_time_ms: int | None = None
    thinking_steps: str = ""
    references: list[dict] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class SessionDetailVO(CamelModel):
    """会话详情视图"""

    id: int = 0
    conversation_id: str = ""
    title: str = ""
    memory_summary: str = ""
    created_at: str | None = None
    chat_mode: str = "auto"
    checkpoint_count: int = 0
    exchange_count: int = 0
    running: bool = False
    message_count: int = 0
    latest_user_message: str = ""
    latest_assistant_message: str = ""
    latest_exchange_id: str | None = None
    latest_turn_status: str = ""
    latest_turn_error_message: str = ""
    selected_document_id: str = ""
    selected_document_name: str = ""
    updated_at: str | None = None
    exchanges: list[dict] = Field(default_factory=list)

