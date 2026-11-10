"""会话历史的请求/响应模型"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.rag.models import Citation, RefusalReason


class SessionMessage(BaseModel):
    """会话中的一条消息。助手消息保存完整引用，文档删除或重建索引后历史仍可读"""

    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: RefusalReason | None = None
    trace_url: str | None = None


class SessionSummary(BaseModel):
    """会话列表项"""

    id: str
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionSummary):
    """会话详情（含全部消息）"""

    messages: list[SessionMessage] = Field(default_factory=list)


class SessionCreate(BaseModel):
    """新建会话。标题可省略，省略时在第一轮问答后自动取问题前 30 字"""

    title: str | None = Field(default=None, max_length=256)
