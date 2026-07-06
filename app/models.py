from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MainIntentCode = Literal[
    "faq",
    "order_service",
    "logistics_service",
    "handoff_service",
    "chitchat",
    "unsupported",
]


SubIntentCode = Literal[
    "faq.general",
    "order_service.query_status",
    "logistics_service.query_status",
    "handoff_service.request_human",
    "chitchat.greeting",
    "chitchat.thanks",
    "unsupported.unknown",
]


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


class ConversationState(BaseModel):
    session_id: str
    user_id: str
    channel: str
    current_main_intent: MainIntentCode = "unsupported"
    current_sub_intent: SubIntentCode = "unsupported.unknown"
    stage: str = "new"
    slots: dict[str, str] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    needs_clarification: bool = False
    summary: str = ""
    message_history: list[dict[str, str]] = Field(default_factory=list)
    last_user_message: str = ""
    intent_result: IntentResult | None = None
    retrieved_faq: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    handoff: bool = False
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
    tool_result: dict[str, Any] | None = None
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
