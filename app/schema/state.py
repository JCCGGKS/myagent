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
    tool: str = ""  # 产生结果的工具（规范名），由 ToolExecutor.run() 从注册表 canonical 自动填入
    kind: Literal["success", "error", "confirmation", "handoff"] = "success"  # 结果性质，不再含工具名
    raw_result: dict[str, Any] | None = None  # 原始业务数据（内部全量，含敏感字段）
    sanitized_result: dict[str, Any] | None = None  # 脱敏副本（经 sanitize_tool_result 处理），跨信任边界的安全版本，绝不直接等于 raw_result


class PendingIntent(BaseModel):
    """多意图场景中，排队等待处理的次要意图（见计划 Phase 3）。

    由 ``IntentResult.extra_intents`` 经多轮裁决层（DialoguePolicy / route）入队，
    用户确认后续办时被激活为 active 意图。
    """

    main_intent: MainIntentCode
    sub_intent: SubIntentCode
    slots: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""


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
    emotion: EmotionState = Field(default_factory=EmotionState)
    needs_clarification: bool = False
    current_action: str = ""
    action_history: list[ActionRecord] = Field(default_factory=list)
    summary: str = ""
    running_summary: str = ""
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    intent_result: IntentResult | None = None
    tool_results: list[ToolExecutionResult] = Field(default_factory=list)
    handoff: bool = False
    handoff_reason: str = ""
    pending_intents: list[PendingIntent] = Field(default_factory=list)
    intent_clarification_count: int = 0
    # R1 二次确认挂起态：发出 confirmation 后、用户确认前，记录待确认操作的负载，
    # 供下一轮「确认/取消」信号确定性拦截（不依赖 LLM 回忆）。结构示例：
    # {"tool": "request_refund", "order_id": "A1002", "refund_type": "refund", "reason": ""}
    # 确认执行 / 取消 / 用户转移话题时清空。
    pending_confirmation: dict[str, Any] | None = None
    reply: str = ""
