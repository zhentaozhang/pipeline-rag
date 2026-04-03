from pydantic import BaseModel, Field


class StopRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    model_config = {"populate_by_name": True}


class SessionIdRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    model_config = {"populate_by_name": True}


class RenameRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    title: str = Field(..., min_length=1, max_length=256)
    model_config = {"populate_by_name": True}


class PinRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    pinned: bool = True
    model_config = {"populate_by_name": True}


class SessionListRequest(BaseModel):
    keyword: str | None = None
    chat_mode: str | None = Field(default=None, alias="chatMode")
    turn_status: str | None = Field(default=None, alias="turnStatus")
    page_no: int = Field(default=1, alias="pageNo")
    page_size: int = Field(default=20, alias="pageSize")
    model_config = {"populate_by_name": True}
