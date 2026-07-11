"""意图与情绪相关的类型与结构。"""

from __future__ import annotations

from typing import Literal, get_args

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


# 子意图的唯一权威定义（与 eval 金标对齐：规则层 consult_policy/request_refund
# 与 LLM 兜底层 damage_refund/no_reason_return/wrong_goods 的并集）。
SubIntentCode = Literal[
    "order_query.query_status",
    "order_query.modify_address",
    "order_query.apply_invoice",
    "logistics.lost_package",
    "logistics.delayed",
    "logistics.not_received",
    "after_sale_refund.request_refund",
    "after_sale_refund.consult_policy",
    "after_sale_refund.damage_refund",
    "after_sale_refund.no_reason_return",
    "after_sale_refund.wrong_goods",
    "complaint.compensate",
    "complaint.service_complaint",
    "handoff_service.request_human",
    "unrecognize.unknown",
    "unsupported_biz.out_of_scope",
]


# 由上面的 Literal 推导出的集合，供运行期校验/提示词生成复用，避免重复硬编码。
MAIN_INTENT_CODES: frozenset[str] = frozenset(get_args(MainIntentCode))
SUB_INTENT_CODES: frozenset[str] = frozenset(get_args(SubIntentCode))


ActionCode = Literal[
    "answer_directly",
    "retrieve_knowledge",
    "query_business_tool",
    "ask_intent_clarification",
    "ask_slot_clarification",
    "handoff_human",
]


EmotionLabel = Literal["neutral", "positive", "negative"]


class EmotionState(BaseModel):
    primary: EmotionLabel = "neutral"
    confidence: float = 0.0


class ExtraIntent(BaseModel):
    """单轮识别出的「次要意图」（多意图场景）。

    主意图走 ``IntentResult`` 顶层字段，其余意图压入 ``IntentResult.extra_intents``，
    由多轮裁决层（DialoguePolicy）排队到 ``state.pending_intents``（见计划 Phase 3）。
    """

    main_intent: MainIntentCode
    sub_intent: SubIntentCode
    confidence: float = 0.0
    slots: dict[str, str] = Field(default_factory=dict)
    reason: str = ""


class IntentResult(BaseModel):
    # 过渡字段：当前语义等同 action，Phase 4 将改为 actions[] 列表（见 intent-recognition-plan.md）。
    sub_intent: SubIntentCode
    main_intent: MainIntentCode
    confidence: float = 0.0
    slots: dict[str, str] = Field(default_factory=dict)
    candidate_intents: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    route_source: str = "rule"
    is_intent_shift: bool = False
    emotion: EmotionState = Field(default_factory=EmotionState)
    handoff_reason: str = ""
    # 多意图场景：除主意图外的其余意图（Phase 3 由 DialoguePolicy 排队到 pending_intents）。
    extra_intents: list[ExtraIntent] = Field(default_factory=list)
