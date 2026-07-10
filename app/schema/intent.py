"""意图与情绪相关的类型与结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MainIntentCode = Literal[
    "order_query",
    "logistics",
    "after_sale_refund",
    "complaint",
    "handoff_service",
    "unrecognize",
    "unsupported_biz",
]


SubIntentCode = Literal[
    "order_query.query_status",
    "order_query.modify_address",
    "order_query.apply_invoice",
    "logistics.lost_package",
    "logistics.delayed",
    "logistics.not_received",
    "after_sale_refund.request_refund",
    "after_sale_refund.consult_policy",
    "after_sale_refund.wrong_goods",
    "complaint.compensate",
    "complaint.service_complaint",
    "handoff_service.request_human",
    "unrecognize.unknown",
    "unsupported_biz.out_of_scope",
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
