"""会话状态与执行产物：动作记录、工具结果、归档状态、会话状态。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schema.intent import (
    EmotionState,
    IntentResult,
    MainIntentCode,
    SubIntentCode,
)


class ActionRecord(BaseModel):
    action_name: str
    status: str = "success"
    summary: str = ""
    created_at: str = ""


class ToolExecutionResult(BaseModel):
    kind: Literal["knowledge", "order_query", "logistics", "aftersale_refund", "handoff", "error"]
    raw_result: dict[str, Any] | None = None
    sanitized_result: dict[str, Any] | None = None
    user_facing_summary: str = ""


class ArchivedTaskState(BaseModel):
    main_intent: MainIntentCode
    sub_intent: SubIntentCode
    stage: str
    slots: dict[str, str] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    summary: str = ""
    archived_reason: str = ""


class ConversationState(BaseModel):
    session_id: str
    user_id: int
    channel: str
    current_main_intent: MainIntentCode = "unrecognize"
    current_sub_intent: SubIntentCode = "unrecognize.unknown"
    stage: str = "new"
    slots: dict[str, str] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    confirmed_slots: list[str] = Field(default_factory=list)
    candidate_intents: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    emotion: EmotionState = Field(default_factory=EmotionState)
    needs_clarification: bool = False
    topic_changed: bool = False
    current_action: str = ""
    latest_action_name: str = ""
    latest_action_result: dict[str, Any] | None = None
    action_history: list[ActionRecord] = Field(default_factory=list)
    current_form_name: str = ""
    current_form_slot_states: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    running_summary: str = ""
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    intent_result: IntentResult | None = None
    tool_result: ToolExecutionResult | None = None
    handoff: bool = False
    handoff_reason: str = ""
    archived_states: list[ArchivedTaskState] = Field(default_factory=list)
    clarification_count: int = 0
    slot_clarification_count: int = 0
    intent_clarification_count: int = 0
    reply: str = ""
