"""对话输入输出：ChatRequest / ChatResponse。

ChatResponse 经 M2 简化后只保留前端真正渲染的两个字段：
- ``reply``：助手回复文本（消息气泡）
- ``session_state``：完整会话状态快照（侧边栏 StatsPanel 经 sessionSnapshot 消费）
其余意图/槽位/阶段/工具结果等字段要么与 session_state 重复、要么当前没有挂载的
渲染组件，故不再下发，避免冗余 payload（详见前端 ConsoleView / StatsPanel）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    channel: str = Field(default="web", min_length=1)


class ChatResponse(BaseModel):
    reply: str
    session_id: str = Field(default="")
    session_state: dict[str, Any] = Field(default_factory=dict)
