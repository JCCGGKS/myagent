from __future__ import annotations

import logging
from typing import Any

from app.schema import ConversationState, IntentResult
from app.business.tools.domain import extract_order_id
from app.business.intent.schema import IntentRuleRegistry, IntentSchemaRegistry
from app.business.intent.llm_fallback import LLMIntentFallbackService
from app.business.context.state_summary import build_state_summary

logger = logging.getLogger(__name__)

# 上下文跟进可承接的上一轮子意图（有 order_id 时）
_SLOT_FOLLOWUP_SUB_INTENTS = {
    "order_query.query_status",
    "logistics.not_received",
    "after_sale_refund.request_refund",
    "after_sale_refund.consult_policy",
}


class IntentRouterService:
    @classmethod
    def from_env(cls, use_llm: bool = True) -> IntentRouterService:
        from app.config import load_llm_config
        from app.business.intent.llm_fallback import LLMIntentFallbackService

        config = load_llm_config()
        llm_fallback = LLMIntentFallbackService(config) if (config.enabled and use_llm) else None
        return cls(llm_fallback_service=llm_fallback)

    def __init__(
        self,
        llm_fallback_service: LLMIntentFallbackService | None = None,
        rule_registry: IntentRuleRegistry | None = None,
    ) -> None:
        self.llm_fallback_service = llm_fallback_service
        self.rule_registry = rule_registry or IntentRuleRegistry()

    def route(self, state: ConversationState, message: str) -> IntentResult:
        lowered = message.casefold()
        order_id = extract_order_id(message)
        previous_main_intent = state.current_main_intent
        previous_sub_intent = state.current_sub_intent
        rules = self.rule_registry.get()

        candidate_intents: list[str] = []
        emotion = self._detect_emotion(lowered, state)

        routing_rules = rules.get("routing_rules", [])
        emotion_keywords = rules.get("emotion_keywords", {})

        logger.debug(
            "Routing message session=%s previous_intent=%s order_id=%s emotion=%s",
            state.session_id, previous_main_intent, order_id, emotion.primary,
        )

        # 规则层：按 routing_rules 列表顺序（即优先级）匹配，命中第一个即返回
        intent = None
        candidate_intents: list[str] = []
        for rule in routing_rules:
            matched, keyword_hit, action_hit = self._rule_matches(rule, lowered, order_id, emotion)
            if not matched:
                continue
            intent, candidate_intents = self._build_intent_from_rule(
                rule, keyword_hit, action_hit, order_id, emotion, previous_main_intent, state
            )
            break

        # 上下文跟进（有 order_id 且上一轮是同类型意图）
        if intent is None and order_id and previous_sub_intent in _SLOT_FOLLOWUP_SUB_INTENTS:
            main_intent = previous_sub_intent.split(".")[0]
            intent = IntentResult(
                main_intent=main_intent,  # type: ignore[arg-type]
                sub_intent=previous_sub_intent,
                confidence=0.86,
                slots={"order_id": order_id},
                route_source="slot_followup",
                emotion=emotion,
            )
            candidate_intents = [main_intent]

        # LLM 兜底分类
        if intent is None:
            llm_intent = self._route_with_llm_fallback(message, previous_sub_intent)
            if llm_intent is not None:
                intent = llm_intent
                candidate_intents = [intent.main_intent, previous_main_intent]
            else:
                intent = IntentResult(
                    main_intent="unrecognize",
                    sub_intent="unrecognize.unknown",
                    confidence=0.2,
                    route_source="fallback",
                    needs_clarification=True,
                    emotion=emotion,
                )
                candidate_intents = ["unrecognize", previous_main_intent]

            logger.info(
                "Routed intent=%s source=%s session=%s",
                intent.main_intent, intent.route_source, state.session_id,
            )

        # 规则置信度低时，尝试用 LLM 结果覆盖
        if intent.route_source == "rule" and intent.confidence < 0.8:
            llm_intent = self._route_with_llm_fallback(message, previous_sub_intent)
            if llm_intent is not None:
                logger.info(
                    "Rule result overridden by LLM: %s.%s -> %s.%s session=%s",
                    intent.main_intent, intent.sub_intent,
                    llm_intent.main_intent, llm_intent.sub_intent,
                    state.session_id,
                )
                intent = llm_intent

        intent.candidate_intents = [item for item in candidate_intents if item]
        intent.is_intent_shift = previous_main_intent not in {"unrecognize", "unsupported_biz", intent.main_intent}
        logger.debug(
            "Routing result intent=%s.%s shift=%s session=%s",
            intent.main_intent, intent.sub_intent, intent.is_intent_shift, state.session_id,
        )
        return intent

    def _route_with_llm_fallback(
        self, message: str, previous_sub_intent: str
    ) -> IntentResult | None:
        if self.llm_fallback_service is None or not self.llm_fallback_service.enabled:
            return None
        return self.llm_fallback_service.classify(message, previous_sub_intent)

    def _rule_matches(
        self, rule: dict[str, Any], lowered: str, order_id: str | None, emotion: Any
    ) -> tuple[bool, bool, bool]:
        """返回 (是否命中, 是否关键词命中, 是否 action 关键词命中)。"""
        keyword_hit = self._contains_any(lowered, rule.get("keywords", []))
        emotion_required = rule.get("emotion")
        emotion_hit = bool(emotion_required) and emotion_required == emotion.primary
        action_keywords = rule.get("action_keywords")
        action_hit = bool(action_keywords) and self._contains_any(lowered, action_keywords)
        matched = keyword_hit or emotion_hit
        return matched, keyword_hit, action_hit

    def _build_intent_from_rule(
        self,
        rule: dict[str, Any],
        keyword_hit: bool,
        action_hit: bool,
        order_id: str | None,
        emotion: Any,
        previous_main_intent: str,
        state: ConversationState,
    ) -> tuple[IntentResult, list[str]]:
        main = rule["intent"]
        sub = rule["sub_intent"]
        if action_hit and rule.get("action_sub_intent"):
            sub = rule["action_sub_intent"]

        if "confidence" in rule:
            conf = rule["confidence"]
        elif rule.get("needs_order"):
            conf = rule["confidence_with_order"] if order_id else rule["confidence_without_order"]
        else:
            conf = rule.get("confidence", 0.8)

        if rule.get("needs_order"):
            needs = order_id is None
        elif rule.get("needs_clarification_when_action_and_no_order"):
            needs = action_hit and order_id is None
        else:
            needs = False

        handoff_reason = rule.get("handoff_reason") if keyword_hit else rule.get("handoff_reason_emotion")

        intent_fields: dict[str, Any] = {
            "main_intent": main,
            "sub_intent": sub,
            "confidence": conf,
            "route_source": "rule",
            "needs_clarification": needs,
            "emotion": emotion,
        }
        if rule.get("risk_level") is not None:
            intent_fields["risk_level"] = rule["risk_level"]
        if handoff_reason:
            intent_fields["handoff_reason"] = handoff_reason

        intent = IntentResult(**intent_fields)
        logger.info("Routed intent=%s.%s source=rule session=%s", main, sub, state.session_id)
        return intent, [main, previous_main_intent]

    def _detect_emotion(self, lowered_message: str, state: ConversationState):
        from app.schema import EmotionState

        rules = self.rule_registry.get()
        emotion_keywords = rules.get("emotion_keywords", {})
        primary = "neutral"
        confidence = 0.6

        if self._contains_any(lowered_message, emotion_keywords.get("negative", [])):
            primary = "negative"
            confidence = 0.9
        elif self._contains_any(lowered_message, emotion_keywords.get("positive", [])):
            primary = "positive"
            confidence = 0.85

        # 上一轮为负面且本轮未显式识别，保留负面记忆（轻微衰减）
        if state.emotion.primary == "negative" and primary == "neutral":
            primary = "negative"
            confidence = max(confidence, state.emotion.confidence - 0.05)

        return EmotionState(primary=primary, confidence=confidence)

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword.casefold() in text for keyword in keywords)


class StateTrackerService:
    def __init__(self, schema_registry: IntentSchemaRegistry | None = None) -> None:
        self.schema_registry = schema_registry or IntentSchemaRegistry()

    def apply(self, state: ConversationState, intent: IntentResult) -> ConversationState:
        previous_main_intent = state.current_main_intent
        previous_sub_intent = state.current_sub_intent
        previous_slots = dict(state.slots)

        logger.debug(
            "StateTracker apply session=%s intent=%s.%s shift=%s",
            state.session_id, intent.main_intent, intent.sub_intent, intent.is_intent_shift,
        )

        if intent.is_intent_shift and previous_main_intent != "unrecognize":
            state.archived_states.append(
                {
                    "main_intent": previous_main_intent,
                    "sub_intent": previous_sub_intent,
                    "stage": state.stage,
                    "slots": previous_slots,
                    "missing_slots": list(state.missing_slots),
                    "summary": state.summary,
                    "archived_reason": f"intent_shift_to_{intent.main_intent}",
                }
            )
            inherited_slots = self._inherit_slots(previous_main_intent, intent.main_intent, previous_slots)
            state.slots = inherited_slots
            state.confirmed_slots = list(inherited_slots.keys())
        elif intent.main_intent == "unrecognize":
            state.slots = {}
            state.confirmed_slots = []

        for key, value in intent.slots.items():
            state.slots[key] = value
            if key not in state.confirmed_slots:
                state.confirmed_slots.append(key)

        state.current_main_intent = intent.main_intent
        state.current_sub_intent = intent.sub_intent
        state.candidate_intents = list(intent.candidate_intents)
        state.risk_level = intent.risk_level
        state.emotion = intent.emotion
        state.needs_clarification = intent.needs_clarification
        state.topic_changed = intent.is_intent_shift
        state.handoff = intent.main_intent == "handoff_service"
        state.handoff_reason = intent.handoff_reason

        schema = self.schema_registry.get(state.current_main_intent)
        required_slots = schema["required_slots"]
        state.missing_slots = [slot for slot in required_slots if not state.slots.get(slot)]
        state.current_form_name = state.current_main_intent
        state.current_form_slot_states = dict(state.slots)

        if state.handoff:
            state.stage = "handoff"
        elif state.missing_slots:
            state.stage = "collecting_info"
        elif state.current_main_intent in {"order_query", "logistics"}:
            state.stage = "executing"
        elif state.current_main_intent == "after_sale_refund":
            state.stage = "executing"
        elif state.current_main_intent in {"complaint", "unrecognize", "unsupported_biz"}:
            state.stage = "responding"
        else:
            state.stage = "unsupported"

        state.summary = build_state_summary(state)
        logger.info(
            "State updated session=%s stage=%s slots=%s missing=%s",
            state.session_id, state.stage, state.slots, state.missing_slots,
        )
        return state

    def build_state_summary(self, state: ConversationState) -> str:
        """委托给共享的自由函数（避免 business 内部循环依赖）。"""
        return build_state_summary(state)

    def _inherit_slots(
        self, previous_intent: str, next_intent: str, previous_slots: dict[str, str]
    ) -> dict[str, str]:
        next_schema = self.schema_registry.get(next_intent)
        inheritable = set(next_schema.get("inheritable", []))
        if previous_intent == next_intent:
            inheritable |= set(previous_slots.keys())
        return {key: value for key, value in previous_slots.items() if key in inheritable}


class HandoffClarificationPolicy:
    def __init__(self, handoff_threshold: int = 3) -> None:
        self.handoff_threshold = handoff_threshold

    def decide(self, state: ConversationState) -> ConversationState:
        if state.handoff:
            state.current_action = "handoff_human"
            logger.info("Policy: handoff forced session=%s", state.session_id)
        elif state.needs_clarification:
            if state.current_main_intent == "unrecognize":
                state.current_action = "ask_intent_clarification"
                state.intent_clarification_count += 1
                logger.info(
                    "Policy: ask_intent_clarification count=%d session=%s",
                    state.intent_clarification_count, state.session_id,
                )
            else:
                state.current_action = "ask_slot_clarification"
                state.slot_clarification_count += 1
                logger.info(
                    "Policy: ask_slot_clarification count=%d missing=%s session=%s",
                    state.slot_clarification_count, state.missing_slots, state.session_id,
                )
        elif state.current_main_intent in {"order_query", "logistics", "after_sale_refund", "complaint"}:
            # 这些意图可能需要工具调用（订单查询、物流查询、RAG 检索等）
            state.current_action = "agent_process"
            logger.debug("Policy: agent_process session=%s", state.session_id)
        else:
            state.current_action = "answer_directly"
            logger.debug("Policy: answer_directly session=%s", state.session_id)

        if (
            state.intent_clarification_count >= self.handoff_threshold
            or state.slot_clarification_count >= self.handoff_threshold
        ):
            state.current_action = "handoff_human"
            state.handoff = True
            state.handoff_reason = "clarification_failed"
            logger.warning(
                "Policy: forced handoff (clarification failed) session=%s",
                state.session_id,
            )

        logger.info("Policy decision action=%s session=%s", state.current_action, state.session_id)
        return state
