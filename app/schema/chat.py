"""对话输入输出：ChatRequest / ChatResponse。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schema.intent import EmotionState, MainIntentCode, SubIntentCode
from app.schema.state import ToolExecutionResult


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    channel: str = Field(default="web", min_length=1)


class ChatResponse(BaseModel):
    reply: str
    main_intent: MainIntentCode
    sub_intent: SubIntentCode
    stage: str
    needs_clarification: bool
    handoff: bool
    slots: dict[str, str]
    missing_slots: list[str] = Field(default_factory=list)
    summary: str = ""
    emotion: EmotionState = Field(default_factory=EmotionState)
    current_action: str = ""
    running_summary: str = ""
    tool_result: ToolExecutionResult | None = None
    session_state: dict[str, Any] = Field(default_factory=dict)
    turn_trace: list[str] = Field(default_factory=list)
