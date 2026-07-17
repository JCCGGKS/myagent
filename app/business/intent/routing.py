from __future__ import annotations

from typing import Any

from app.schema import ConversationState, IntentResult, EmotionState
from app.business.tools.domain import extract_order_id
from app.business.intent.schema import IntentRuleRegistry, IntentSchemaRegistry
from app.business.intent.policy import DialoguePolicy
from app.business.intent.llm_fallback import LLMIntentFallbackService
from app.business.context.state_summary import build_state_summary
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("intent")

# 上下文跟进可承接的上一轮子意图（有 order_id 时）
_SLOT_FOLLOWUP_SUB_INTENTS = {
    "order_query.query_status",
    "logistics.not_received",
    "after_sale_refund.request_refund",
    "after_sale_refund.consult_policy",
}


class IntentRouterService:
    @classmethod
    def from_env(
        cls, use_llm: bool = True, override_threshold: float = 0.7
    ) -> IntentRouterService:
        from app.config import load_llm_config
        from app.business.intent.llm_fallback import LLMIntentFallbackService

        config = load_llm_config()
        llm_fallback = LLMIntentFallbackService(config) if (config.enabled and use_llm) else None
        return cls(llm_fallback_service=llm_fallback, override_threshold=override_threshold)

    def __init__(
        self,
        llm_fallback_service: LLMIntentFallbackService | None = None,
        rule_registry: IntentRuleRegistry | None = None,
        override_threshold: float = 0.7,
    ) -> None:
        self.llm_fallback_service = llm_fallback_service
        self.rule_registry = rule_registry or IntentRuleRegistry()
        # LLM 覆盖阈值：规则命中且 confidence < override_threshold 时才用 LLM 覆盖。
        # 调优方法见 eval 文档「覆盖阈值调优方法」。设为 >=2.0 可强制覆盖所有规则命中（评估用）。
        self.override_threshold = override_threshold

    async def route(self, state: ConversationState, message: str) -> IntentResult:
        lowered = message.casefold()
        order_id = extract_order_id(message)
        previous_main_intent = state.current_main_intent
        previous_sub_intent = state.current_sub_intent
        rules = self.rule_registry.get()

        candidate_intents: list[str] = []
        rule_emotion = self._detect_emotion(lowered)
        llm_emotion: EmotionState | None = None

        routing_rules = rules.get("routing_rules", [])

        logger.debug(
            _tagged("intent", "Routing message session=%s previous_intent=%s order_id=%s rule_emotion=%s"),
            state.session_id, previous_main_intent, order_id, rule_emotion.primary,
        )

        # 规则层：按 routing_rules 列表顺序（即优先级）匹配，命中第一个即返回
        intent = None
        candidate_intents: list[str] = []
        for rule in routing_rules:
            matched, keyword_hit, action_hit = self._rule_matches(rule, lowered, order_id, rule_emotion)
            if not matched:
                continue
            intent, candidate_intents = self._build_intent_from_rule(
                rule, keyword_hit, action_hit, order_id, rule_emotion, previous_main_intent, state
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
                emotion=rule_emotion,
            )
            candidate_intents = [main_intent]

        # LLM 兜底分类
        if intent is None:
            llm_intent = await self._route_with_llm_fallback(message, state)
            if llm_intent is not None:
                llm_emotion = llm_intent.emotion
                # 合并规则层已抽出的实体，避免 LLM 漏抽订单号
                if order_id:
                    llm_intent.slots.setdefault("order_id", order_id)
                intent = llm_intent
                candidate_intents = [intent.main_intent, previous_main_intent]
            else:
                intent = IntentResult(
                    main_intent="unrecognize",
                    sub_intent="unrecognize.unknown",
                    confidence=0.2,
                    route_source="fallback",
                    needs_clarification=True,
                    emotion=rule_emotion,
                )
                candidate_intents = ["unrecognize", previous_main_intent]

            logger.info(
                _tagged("intent", "Routed intent=%s source=%s session=%s"),
                intent.main_intent, intent.route_source, state.session_id,
            )

        # 规则置信度低时，尝试用 LLM 结果覆盖。
        # 阈值由 self.override_threshold 控制（默认 0.7）：
        # 0.76/0.78 这类高置信规则结果不再被 LLM 覆盖改错
        # （对比评估显示覆盖会反噬 ~6 个已正确的规则命中）。
        # 调优时可用 eval/run_eval.py --sweep-threshold 扫描最优阈值。
        if intent.route_source == "rule" and intent.confidence < self.override_threshold:
            llm_intent = await self._route_with_llm_fallback(message, state)
            if llm_intent is not None:
                llm_emotion = llm_intent.emotion
                logger.info(
                    _tagged("intent", "Rule result overridden by LLM: %s.%s -> %s.%s session=%s"),
                    intent.main_intent, intent.sub_intent,
                    llm_intent.main_intent, llm_intent.sub_intent,
                    state.session_id,
                )
                intent = llm_intent

        # 统一把规则层抽取到的实体并入 slots：规则/槽跟进路径构造 IntentResult 时
        # 不带 slots，若不在此补齐，state.slots 会为空，导致跨意图继承（如 order_id）
        # 失效——用户先查订单再退款时会被重复追问订单号（见回归测试）。
        if order_id and not intent.slots.get("order_id"):
            intent.slots["order_id"] = order_id

        # 情绪合并（规则 + LLM 双路）+ 负面记忆回退：LLM 无结果取规则；规则非 neutral
        # 优先（关键词确定性强）；规则 neutral 但 LLM 给出情绪则补盲区；都 neutral 取 neutral。
        # 合并后仍 neutral 且上一轮为 negative → 沿用负面（轻微衰减），避免多轮愤怒断档。
        merged = self._merge_emotion(rule_emotion, llm_emotion)
        if merged.primary == "neutral" and state.emotion.primary == "negative":
            merged = EmotionState(primary="negative", confidence=max(merged.confidence, state.emotion.confidence - 0.05))
        intent.emotion = merged

        intent.candidate_intents = [item for item in candidate_intents if item]
        intent.is_intent_shift = previous_main_intent not in {"unrecognize", "unsupported_biz", intent.main_intent}
        logger.debug(
            _tagged("intent", "Routing result intent=%s.%s shift=%s emotion=%s session=%s"),
            intent.main_intent, intent.sub_intent, intent.is_intent_shift, merged.primary, state.session_id,
        )
        return intent

    async def _route_with_llm_fallback(
        self, message: str, state: ConversationState
    ) -> IntentResult | None:
        if self.llm_fallback_service is None or not self.llm_fallback_service.enabled:
            return None
        logger.debug(_tagged("intent", "LLM fallback classify session=%s"), state.session_id)
        return await self.llm_fallback_service.classify(message, state)

    def _rule_matches(
        self, rule: dict[str, Any], lowered: str, order_id: str | None, emotion: Any
    ) -> tuple[bool, bool, bool]:
        """返回 (是否命中, 是否关键词命中, 是否 action 关键词命中)。"""
        keyword_hit = self._contains_any(lowered, rule.get("keywords", []))
        emotion_required = rule.get("emotion")
        emotion_hit = bool(emotion_required) and emotion_required == emotion.primary
        action_keywords = rule.get("action_keywords")
        action_hit = bool(action_keywords) and self._contains_any(lowered, action_keywords)
        # action_keywords 也是合法的意图触发词（如「退掉」「我要退款」这类强动作表述可能
        # 不含基础关键词），必须能独立命中规则，否则会漏匹配、退化到兜底、错失 needs_clarification。
        matched = keyword_hit or emotion_hit or action_hit
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

        # 槽位继承：若 state 已持有 order_id（上一轮继承），即使本轮消息未
        # 复述，也不应再追问订单号——否则「澄清后未重置 need 字段」会让
        # LLM 澄清节点再次向用户发问（见回归 test_route_should_not_ask_order_id_when_inherited）。
        inherited_order = bool(state.slots.get("order_id"))
        if rule.get("needs_order"):
            needs = order_id is None and not inherited_order
        elif rule.get("needs_clarification_when_no_order"):
            # 缺订单号即需澄清：覆盖「强动作词」（退掉/我要退款）与「基础关键词」
            # （退款/退货/不想要了）。否则「退款」这类仅含基础关键词的消息会漏判为
            # 无需澄清的 consult，直接进 agent_node 触发 RAG 检索并以「检索到 0 条」
            # 这类无效内容当作最终回复（见回归 06_工具调用）。
            needs = (action_hit or keyword_hit) and order_id is None and not inherited_order
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
        logger.info(_tagged("intent", "Routed intent=%s.%s source=rule session=%s"), main, sub, state.session_id)
        return intent, [main, previous_main_intent]

    def _detect_emotion(self, lowered_message: str) -> EmotionState:
        """规则侧情绪识别（关键词，含否定词消歧）。

        仅产出「本轮文本」的规则情绪，不含多轮记忆——记忆回退统一在
        ``_merge_emotion`` 里处理，避免规则与 LLM 合并后再叠加记忆导致逻辑分散。
        """
        rules = self.rule_registry.get()
        emotion_keywords = rules.get("emotion_keywords", {})
        primary = "neutral"
        confidence = 0.6

        if self._emotion_hit(lowered_message, emotion_keywords.get("negative", [])):
            primary = "negative"
            confidence = 0.9
        elif self._emotion_hit(lowered_message, emotion_keywords.get("positive", [])):
            primary = "positive"
            confidence = 0.85

        return EmotionState(primary=primary, confidence=confidence)

    # 否定前缀：出现在情绪关键词前（≤2 字）时，该关键词视为被否定（如「不生气」「没投诉」）。
    # 含「不太」：让「不太满意」「不太生气」因关键词被否定而回落 neutral（不误判 positive/negative），
    # 真实负面由 LLM 路径补（见 plans/emotion-recognition-soothing-plan.md 1.2）。
    _NEGATION_PREFIXES = ("不", "没", "别", "未", "无", "莫", "甭", "不用", "不要", "没有", "未能", "不太")

    def _emotion_hit(self, text: str, keywords: list[str]) -> bool:
        """否定词感知的关键词命中：关键词命中且前方无否定前缀才算命中。"""
        for kw in keywords:
            idx = text.find(kw)
            while idx != -1:
                before = text[max(0, idx - 2):idx]
                if not any(before.endswith(neg) for neg in self._NEGATION_PREFIXES):
                    return True
                idx = text.find(kw, idx + 1)
        return False

    def _merge_emotion(self, rule_emotion: EmotionState, llm_emotion: EmotionState | None) -> EmotionState:
        """规则 + LLM 双路情绪合并：

        - LLM 无结果 → 取规则；
        - 规则已识别非 neutral（关键词确定性强）→ 优先取规则；
        - 规则 neutral 但 LLM 给出情绪 → 取 LLM（补「无关键词但语义负面」盲区，如「你们这服务我真服了」）；
        - 都 neutral → neutral。
        """
        if llm_emotion is None:
            return rule_emotion
        if rule_emotion.primary != "neutral":
            return rule_emotion
        if llm_emotion.primary != "neutral":
            return llm_emotion
        return rule_emotion

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword.casefold() in text for keyword in keywords)


class StateTrackerService:
    def __init__(self, schema_registry: IntentSchemaRegistry | None = None) -> None:
        self.schema_registry = schema_registry or IntentSchemaRegistry()
        # 多轮覆盖决策抽离到独立 DialoguePolicy（Phase 2），apply 负责把决策写入 state。
        self.policy = DialoguePolicy(schema_registry=self.schema_registry)

    def apply(self, state: ConversationState, intent: IntentResult) -> ConversationState:
        previous_main_intent = state.current_main_intent
        previous_sub_intent = state.current_sub_intent
        previous_slots = dict(state.slots)

        logger.debug(
            _tagged("intent", "StateTracker apply session=%s intent=%s.%s shift=%s"),
            state.session_id, intent.main_intent, intent.sub_intent, intent.is_intent_shift,
        )

        if self.policy.should_archive(intent, previous_main_intent):
            inherited_slots = self.policy.inherit_slots(previous_main_intent, intent.main_intent, previous_slots)
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
        state.emotion = intent.emotion
        state.needs_clarification = intent.needs_clarification
        state.handoff = intent.main_intent == "handoff_service"
        state.handoff_reason = intent.handoff_reason

        schema = self.schema_registry.get(state.current_main_intent)
        required_slots = schema["required_slots"]
        state.missing_slots = [slot for slot in required_slots if not state.slots.get(slot)]

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
            _tagged("intent", "State updated session=%s stage=%s slots=%s missing=%s"),
            state.session_id, state.stage, state.slots, state.missing_slots,
        )
        return state

    def build_state_summary(self, state: ConversationState) -> str:
        """委托给共享的自由函数（避免 business 内部循环依赖）。"""
        return build_state_summary(state)


class HandoffClarificationPolicy:
    # 槽位齐全且存在可用工具的意图：可直接自助，永不被「澄清失败」强制转人工。
    _SELF_SERVICE_INTENTS = {
        "order_query",
        "logistics",
        "after_sale_refund",
    }

    def __init__(self, handoff_threshold: int = 3) -> None:
        self.handoff_threshold = handoff_threshold

    def decide(self, state: ConversationState) -> ConversationState:
        if state.handoff:
            state.current_action = "handoff_human"
            logger.info(_tagged("intent", "Policy: handoff forced session=%s"), state.session_id)
        elif state.needs_clarification:
            if state.current_main_intent == "unrecognize":
                state.current_action = "ask_intent_clarification"
                state.intent_clarification_count += 1
                logger.info(
                    _tagged("intent", "Policy: ask_intent_clarification count=%d session=%s"),
                    state.intent_clarification_count, state.session_id,
                )
            else:
                state.current_action = "ask_slot_clarification"
                logger.info(
                    _tagged("intent", "Policy: ask_slot_clarification missing=%s session=%s"),
                    state.missing_slots, state.session_id,
                )
        elif state.current_main_intent in self._SELF_SERVICE_INTENTS | {"complaint"}:
            # 这些意图可能需要工具调用（订单查询、物流查询、RAG 检索等）
            state.current_action = "agent_process"
            logger.debug(_tagged("intent", "Policy: agent_process session=%s"), state.session_id)
        else:
            state.current_action = "answer_directly"
            logger.debug(_tagged("intent", "Policy: answer_directly session=%s"), state.session_id)

        # 本轮已成功解析/补齐槽位 → 清零澄清计数，避免历史包袱滚雪球。
        # 阈值因此变为「连续澄清失败次数」而非「会话累计」，更贴合
        # 「真卡住才升级」语义。
        if not state.needs_clarification:
            state.intent_clarification_count = 0

        # 兜底出口（防死循环）：仅在「本轮仍需澄清」且为真正听不懂
        # （intent 澄清失败，缺单号等槽位澄清不计入）且达阈值时强制转人工。
        # 槽位已齐、工具可用的自助意图（如已知 A1001 的订单详情）绝不强制升级。
        stuck = state.needs_clarification
        self_service = (
            not state.missing_slots
            and state.current_main_intent in self._SELF_SERVICE_INTENTS
        )
        if (
            stuck
            and not self_service
            and state.intent_clarification_count >= self.handoff_threshold
        ):
            state.current_action = "handoff_human"
            state.handoff = True
            state.handoff_reason = "clarification_failed"
            logger.warning(
                _tagged("intent", "Policy: forced handoff (clarification failed) session=%s"),
                state.session_id,
            )

        logger.info(_tagged("intent", "Policy decision action=%s session=%s"), state.current_action, state.session_id)
        return state
