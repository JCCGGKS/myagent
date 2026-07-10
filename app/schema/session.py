"""会话管理相关的请求/响应结构。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
