from __future__ import annotations

import logging
from typing import Any

from app.models import ConversationState, IntentResult
from app.rag import KnowledgeBaseService
from app.services.domain import extract_order_id
from app.services.intent_schema import IntentRuleRegistry, IntentSchemaRegistry
from app.services.llm_fallback import LLMIntentFallbackService

logger = logging.getLogger(__name__)


class IntentRouterService:
    @classmethod
    def from_env(cls, use_llm: bool = True) -> IntentRouterService:
        from app.config import load_llm_config
        from app.rag import KnowledgeBaseService
        from app.services.llm_fallback import LLMIntentFallbackService

        config = load_llm_config()
        kb = KnowledgeBaseService()
        llm_fallback = LLMIntentFallbackService(config) if (config.enabled and use_llm) else None
        return cls(kb, llm_fallback_service=llm_fallback)

    def __init__(
        self,
        knowledge_base: KnowledgeBaseService,
        llm_fallback_service: LLMIntentFallbackService | None = None,
        rule_registry: IntentRuleRegistry | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.llm_fallback_service = llm_fallback_service
        self.rule_registry = rule_registry or IntentRuleRegistry()

    def route(self, state: ConversationState, message: str) -> IntentResult:
        lowered = message.casefold()
        order_id = extract_order_id(message)
        previous_main_intent = state.current_main_intent
        previous_sub_intent = state.current_sub_intent
        rules = self.rule_registry.get()

        knowledge_hits = self.knowledge_base.search(message)
        candidate_intents: list[str] = []
        emotion = self._detect_emotion(lowered, state)
        has_handoff_keyword = self._contains_any(lowered, rules.get("handoff_keywords", []))
        has_logistics_keyword = self._contains_any(lowered, rules.get("logistics_keywords", []))
        has_order_keyword = self._contains_any(lowered, rules.get("order_keywords", []))
        has_refund_keyword = self._contains_any(lowered, rules.get("refund_keywords", []))
        has_refund_action_keyword = self._contains_any(lowered, rules.get("refund_action_keywords", []))
        has_refund_rule_keyword = self._contains_any(lowered, rules.get("refund_rule_keywords", []))
        has_greeting_keyword = self._contains_any(lowered, rules.get("greeting_keywords", []))
        has_thanks_keyword = self._contains_any(lowered, rules.get("thanks_keywords", []))

        logger.debug(
            "Routing message session=%s previous_intent=%s order_id=%s "
            "handoff_kw=%s logistics_kw=%s order_kw=%s refund_kw=%s greeting_kw=%s thanks_kw=%s "
            "emotion=%s",
            state.session_id, previous_main_intent, order_id,
            has_handoff_keyword, has_logistics_keyword, has_order_keyword,
            has_refund_keyword, has_greeting_keyword, has_thanks_keyword,
            emotion.primary,
        )

        if has_handoff_keyword or emotion.primary in {"angry", "urgent"}:
            intent = IntentResult(
                main_intent="handoff_service",
                sub_intent="handoff_service.request_human",
                confidence=0.99,
                route_source="rule",
                risk_level="medium" if has_handoff_keyword else "high",
                emotion=emotion,
                handoff_reason="user_request" if has_handoff_keyword else "emotion_escalation",
            )
            candidate_intents = ["handoff_service", previous_main_intent]
            logger.info(
                "Routed intent=handoff_service reason=%s emotion=%s session=%s",
                intent.handoff_reason, emotion.primary, state.session_id,
            )
        elif has_logistics_keyword:
            slots = {"order_id": order_id} if order_id else {}
            intent = IntentResult(
                main_intent="logistics_service",
                sub_intent="logistics_service.query_status",
                confidence=0.9 if order_id else 0.78,
                slots=slots,
                route_source="rule",
                needs_clarification=order_id is None,
                emotion=emotion,
            )
            candidate_intents = ["logistics_service", "order_service"]
            logger.info(
                "Routed intent=logistics_service confidence=%.2f order_id=%s session=%s",
                intent.confidence, order_id, state.session_id,
            )
        elif has_order_keyword:
            slots = {"order_id": order_id} if order_id else {}
            intent = IntentResult(
                main_intent="order_service",
                sub_intent="order_service.query_status",
                confidence=0.9 if order_id else 0.76,
                slots=slots,
                route_source="rule",
                needs_clarification=order_id is None,
                emotion=emotion,
            )
            candidate_intents = ["order_service", "logistics_service"]
            logger.info(
                "Routed intent=order_service confidence=%.2f order_id=%s session=%s",
                intent.confidence, order_id, state.session_id,
            )
        elif has_refund_keyword:
            slots = {"order_id": order_id} if order_id else {}
            sub_intent = (
                "refund_service.request_refund"
                if has_refund_action_keyword
                else "refund_service.consult_policy"
            )
            intent = IntentResult(
                main_intent="refund_service",
                sub_intent=sub_intent,
                confidence=0.88 if order_id or has_refund_rule_keyword else 0.8,
                slots=slots,
                route_source="rule",
                needs_clarification=has_refund_action_keyword and order_id is None,
                emotion=emotion,
            )
            candidate_intents = ["refund_service", "faq"]
            logger.info(
                "Routed intent=%s confidence=%.2f order_id=%s session=%s",
                sub_intent, intent.confidence, order_id, state.session_id,
            )
        elif has_greeting_keyword:
            intent = IntentResult(
                main_intent="chitchat",
                sub_intent="chitchat.greeting",
                confidence=0.95,
                route_source="rule",
                emotion=emotion,
            )
            candidate_intents = ["chitchat"]
            logger.info("Routed intent=chitchat.greeting session=%s", state.session_id)
        elif has_thanks_keyword:
            intent = IntentResult(
                main_intent="chitchat",
                sub_intent="chitchat.thanks",
                confidence=0.95,
                route_source="rule",
                emotion=emotion,
            )
            candidate_intents = ["chitchat"]
            logger.info("Routed intent=chitchat.thanks session=%s", state.session_id)
        elif order_id and previous_sub_intent in {
            "order_service.query_status",
            "logistics_service.query_status",
            "refund_service.request_refund",
        }:
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
            logger.info(
                "Routed via slot_followup intent=%s order_id=%s session=%s",
                previous_sub_intent, order_id, state.session_id,
            )
        elif knowledge_hits:
            intent = IntentResult(
                main_intent="faq",
                sub_intent="faq.general",
                confidence=knowledge_hits[0].score,
                route_source="rule",
                emotion=emotion,
            )
            candidate_intents = ["faq"]
            logger.info(
                "Routed intent=faq (knowledge hit) score=%.2f session=%s",
                knowledge_hits[0].score, state.session_id,
            )
        else:
            # 规则未命中，尝试 LLM 兜底
            llm_intent = self._route_with_llm_fallback(message, previous_sub_intent)
            if llm_intent is not None:
                intent = llm_intent
                candidate_intents = [intent.main_intent, previous_main_intent]
            else:
                intent = IntentResult(
                    main_intent="unsupported",
                    sub_intent="unsupported.unknown",
                    confidence=0.2,
                    route_source="fallback",
                    needs_clarification=True,
                    emotion=emotion,
                )
                candidate_intents = ["unsupported", previous_main_intent]

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
        intent.is_intent_shift = previous_main_intent not in {"unsupported", intent.main_intent}
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

    def _detect_emotion(self, lowered_message: str, state: ConversationState):
        from app.models.schemas import EmotionState

        rules = self.rule_registry.get()
        primary = "neutral"
        confidence = 0.6
        trend = "stable"

        if self._contains_any(lowered_message, rules.get("angry_keywords", [])):
            primary = "angry"
            confidence = 0.9
            trend = "escalating"
        elif self._contains_any(lowered_message, rules.get("urgent_keywords", [])):
            primary = "urgent"
            confidence = 0.85
            trend = "escalating"
        elif self._contains_any(lowered_message, rules.get("confused_keywords", [])):
            primary = "confused"
            confidence = 0.82
        elif self._contains_any(lowered_message, rules.get("anxious_keywords", [])):
            primary = "anxious"
            confidence = 0.8
        elif self._contains_any(lowered_message, rules.get("happy_keywords", [])):
            primary = "happy"
            confidence = 0.75
            trend = "deescalating"

        if state.emotion.primary in {"anxious", "confused"} and primary == "neutral":
            primary = state.emotion.primary
            confidence = max(confidence, state.emotion.confidence - 0.05)

        return EmotionState(primary=primary, confidence=confidence, trend=trend)

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

        if intent.is_intent_shift and previous_main_intent != "unsupported":
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
        elif intent.main_intent == "unsupported":
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
        elif state.current_main_intent in {"order_service", "logistics_service"}:
            state.stage = "executing"
        elif state.current_main_intent == "refund_service":
            state.stage = "retrieving" if state.current_sub_intent == "refund_service.consult_policy" else "clarifying"
        elif state.current_main_intent == "faq":
            state.stage = "retrieving"
        elif state.current_main_intent == "chitchat":
            state.stage = "responding"
        else:
            state.stage = "unsupported"

        state.summary = self.build_state_summary(state)
        logger.info(
            "State updated session=%s stage=%s slots=%s missing=%s",
            state.session_id, state.stage, state.slots, state.missing_slots,
        )
        return state

    def build_state_summary(self, state: ConversationState) -> str:
        parts = [
            f"用户当前主意图={state.current_main_intent}",
            f"子意图={state.current_sub_intent}",
        ]
        if state.slots:
            parts.append(f"已确认槽位={state.slots}")
        if state.missing_slots:
            parts.append(f"仍缺槽位={state.missing_slots}")
        if state.latest_action_result:
            parts.append(f"最近动作结果={state.latest_action_result}")
        return "；".join(parts)

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
            if state.current_main_intent == "unsupported":
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
        elif state.current_main_intent in {"faq", "refund_service"}:
            state.current_action = "retrieve_knowledge"
            logger.debug("Policy: retrieve_knowledge session=%s", state.session_id)
        elif state.current_main_intent in {"order_service", "logistics_service"}:
            state.current_action = "query_business_tool"
            logger.debug("Policy: query_business_tool session=%s", state.session_id)
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
