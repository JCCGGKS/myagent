from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MainIntentCode = Literal[
    "faq",
    "order_service",
    "logistics_service",
    "refund_service",
    "handoff_service",
    "chitchat",
    "unsupported",
]


SubIntentCode = Literal[
    "faq.general",
    "order_service.query_status",
    "logistics_service.query_status",
    "refund_service.consult_policy",
    "refund_service.request_refund",
    "handoff_service.request_human",
    "chitchat.greeting",
    "chitchat.thanks",
    "unsupported.unknown",
]


ActionCode = Literal[
    "answer_directly",
    "retrieve_knowledge",
    "query_business_tool",
    "ask_intent_clarification",
    "ask_slot_clarification",
    "handoff_human",
]


EmotionLabel = Literal["neutral", "confused", "anxious", "angry", "urgent", "happy"]


class EmotionState(BaseModel):
    primary: EmotionLabel = "neutral"
    confidence: float = 0.0
    trend: Literal["stable", "escalating", "deescalating"] = "stable"


class ActionRecord(BaseModel):
    action_name: str
    status: str = "success"
    summary: str = ""
    created_at: str = ""


class KnowledgeHit(BaseModel):
    faq_key: str
    question: str
    answer: str
    score: float = 0.0
    doc_type: str = "faq"


class ToolExecutionResult(BaseModel):
    kind: Literal["knowledge", "order", "logistics", "handoff"]
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


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    channel: str = Field(default="web", min_length=1)


class IntentResult(BaseModel):
    main_intent: MainIntentCode
    sub_intent: SubIntentCode
    confidence: float = 0.0
    slots: dict[str, str] = Field(default_factory=dict)
    candidate_intents: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    route_source: str = "rule"
    is_intent_shift: bool = False
    emotion: EmotionState = Field(default_factory=EmotionState)
    handoff_reason: str = ""


class ConversationState(BaseModel):
    session_id: str
    user_id: str
    channel: str
    current_main_intent: MainIntentCode = "unsupported"
    current_sub_intent: SubIntentCode = "unsupported.unknown"
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
    message_history: list[dict[str, str]] = Field(default_factory=list)
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    last_user_message: str = ""
    intent_result: IntentResult | None = None
    retrieved_knowledge: list[KnowledgeHit] = Field(default_factory=list)
    tool_result: ToolExecutionResult | None = None
    handoff: bool = False
    handoff_reason: str = ""
    archived_states: list[ArchivedTaskState] = Field(default_factory=list)
    clarification_count: int = 0
    slot_clarification_count: int = 0
    intent_clarification_count: int = 0
    reply: str = ""


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


class OrderInfo(BaseModel):
    order_id: str
    status: str
    product_name: str
    amount: float


class LogisticsEvent(BaseModel):
    time: str
    status: str


class LogisticsInfo(BaseModel):
    order_id: str
    tracking_status: str
    timeline: list[LogisticsEvent]


class HandoffResult(BaseModel):
    ticket_id: str
    summary: str
