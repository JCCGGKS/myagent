"""会话管理相关的请求/响应结构。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionInitRequest(BaseModel):
    channel: str = Field(default="web", min_length=1)
    title: str = Field(default="新会话", max_length=128)


class SessionInitResponse(BaseModel):
    session_id: str
    title: str = "新会话"


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
