"""多意图（pending_intents）单元测试（计划 Phase 3）。"""

import asyncio
from unittest.mock import MagicMock

from app.schema import ConversationState, ExtraIntent, IntentResult, PendingIntent
from app.business.intent.routing import IntentRouterService


def _make_router() -> IntentRouterService:
    rule_registry = MagicMock()
    rule_registry.get.return_value = {"emotion_keywords": {}, "routing_rules": []}
    return IntentRouterService(rule_registry=rule_registry)


class MultiIntentTestCase:
    def test_multi_intent_enqueues_pending(self):
        svc = _make_router()

        async def fake_llm(message, prev):
            return IntentResult(
                main_intent="logistics",
                sub_intent="logistics.not_received",
                slots={"order_id": "A1001"},
                confidence=0.9,
                extra_intents=[
                    ExtraIntent(
                        main_intent="after_sale_refund",
                        sub_intent="after_sale_refund.request_refund",
                        slots={"order_id": "A1001"},
                        confidence=0.85,
                    )
                ],
            )

        svc._route_with_llm_fallback = fake_llm
        state = ConversationState(session_id="s", user_id=1, channel="web")
        result = asyncio.run(svc.route(state, "查订单A1001物流另外我要退款"))

        assert result.main_intent == "logistics"
        assert len(state.pending_intents) == 1
        assert state.pending_intents[0].main_intent == "after_sale_refund"
        assert state.pending_intents[0].slots == {"order_id": "A1001"}

    def test_continue_signal_activates_pending(self):
        svc = _make_router()

        async def fake_llm(message, prev):
            return IntentResult(
                main_intent="unrecognize",
                sub_intent="unrecognize.unknown",
                confidence=0.2,
                needs_clarification=True,
            )

        svc._route_with_llm_fallback = fake_llm
        state = ConversationState(session_id="s", user_id=1, channel="web")
        state.pending_intents.append(
            PendingIntent(main_intent="after_sale_refund", sub_intent="after_sale_refund.request_refund", slots={"order_id": "A1001"})
        )
        result = asyncio.run(svc.route(state, "继续"))

        assert result.main_intent == "after_sale_refund"
        assert result.route_source == "pending_advance"
        assert state.pending_intents == []

    def test_explicit_pending_intent_is_deduped(self):
        svc = _make_router()

        async def fake_llm(message, prev):
            return IntentResult(
                main_intent="after_sale_refund",
                sub_intent="after_sale_refund.request_refund",
                slots={"order_id": "A1001"},
                confidence=0.85,
            )

        svc._route_with_llm_fallback = fake_llm
        state = ConversationState(session_id="s", user_id=1, channel="web")
        state.pending_intents.append(
            PendingIntent(main_intent="after_sale_refund", sub_intent="after_sale_refund.request_refund", slots={"order_id": "A1001"})
        )
        result = asyncio.run(svc.route(state, "我要退款"))

        assert result.main_intent == "after_sale_refund"
        # 当前意图恰好是待处理意图 → 出队，不再待处理
        assert state.pending_intents == []

    def test_no_double_enqueue_when_clarifying(self):
        """上一轮仍在澄清中时，本轮不应新开意图入队（新消息守卫）。"""
        svc = _make_router()

        async def fake_llm(message, prev):
            return IntentResult(
                main_intent="logistics",
                sub_intent="logistics.not_received",
                slots={"order_id": "A1001"},
                confidence=0.9,
                extra_intents=[
                    ExtraIntent(main_intent="after_sale_refund", sub_intent="after_sale_refund.request_refund", slots={}, confidence=0.85)
                ],
            )

        svc._route_with_llm_fallback = fake_llm
        state = ConversationState(session_id="s", user_id=1, channel="web")
        state.needs_clarification = True  # 模拟上一轮仍在澄清
        result = asyncio.run(svc.route(state, "查物流另外退款"))

        assert state.pending_intents == []


class IntentInheritanceTestCase:
    """回归：先查订单（带订单号）再退款，order_id 应跨意图继承，不重复追问。"""

    def test_order_id_inherited_across_intent_shift(self):
        from app.business.intent.routing import StateTrackerService
        from app.business.intent.schema import IntentRuleRegistry, IntentSchemaRegistry

        rule_registry = IntentRuleRegistry()
        svc = IntentRouterService(rule_registry=rule_registry)
        tracker = StateTrackerService(schema_registry=IntentSchemaRegistry())

        # 第一轮：查订单 A1001（规则命中，需订单号）
        state = ConversationState(session_id="s", user_id=1, channel="web")
        intent1 = asyncio.run(svc.route(state, "订单A1001的发货情况"))
        tracker.apply(state, intent1)
        assert state.current_main_intent == "order_query"
        # 修复点：规则路径也要把抽取到的 order_id 并入 slots
        assert state.slots.get("order_id") == "A1001"

        # 第二轮：退款（规则不命中 → LLM 识别，但消息本身无订单号）
        async def fake_llm(message, prev):
            return IntentResult(
                main_intent="after_sale_refund",
                sub_intent="after_sale_refund.request_refund",
                slots={},  # LLM 不知道订单号
                confidence=0.85,
            )

        svc._route_with_llm_fallback = fake_llm
        intent2 = asyncio.run(svc.route(state, "把它退了吧"))
        tracker.apply(state, intent2)
        assert state.current_main_intent == "after_sale_refund"
        # 关键断言：order_id 应从上一轮继承，无需再追问
        assert state.slots.get("order_id") == "A1001"
        assert state.missing_slots == []
