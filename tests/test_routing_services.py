import unittest
from unittest.mock import MagicMock

from app.models import ConversationState, IntentResult
from app.services.intent_schema import IntentRuleRegistry, IntentSchemaRegistry
from app.services.routing import (
    HandoffClarificationPolicy,
    IntentRouterService,
    StateTrackerService,
)


class RoutingServicesTestCase(unittest.TestCase):
    def test_intent_schema_registry_should_load_default_yaml_schema(self) -> None:
        registry = IntentSchemaRegistry()

        schema = registry.get("after_sale_refund")

        self.assertEqual(schema["required_slots"], ["order_id"])
        self.assertIn("refund_reason", schema["optional_slots"])

    def test_intent_rule_registry_should_load_default_yaml_rules(self) -> None:
        registry = IntentRuleRegistry()

        rules = registry.get()

        self.assertIn("handoff_keywords", rules)
        self.assertIn("转人工", rules["handoff_keywords"])
        self.assertIn("complaint_keywords", rules)

    def test_intent_router_should_detect_handoff(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s1", user_id="u1", channel="web")

        intent = router.route(state, "我要转人工")

        self.assertEqual(intent.main_intent, "handoff_service")
        self.assertEqual(intent.sub_intent, "handoff_service.request_human")

    def test_intent_router_should_detect_complaint(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s2", user_id="u1", channel="web")

        intent = router.route(state, "你们什么破平台，投诉")

        self.assertEqual(intent.main_intent, "complaint")
        self.assertEqual(intent.risk_level, "high")

    def test_intent_router_should_detect_logistics(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s3", user_id="u1", channel="web")

        intent = router.route(state, "我的物流到哪了")

        self.assertEqual(intent.main_intent, "logistics")
        self.assertTrue(intent.needs_clarification)  # 缺 order_id

    def test_intent_router_should_detect_order_query(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s4", user_id="u1", channel="web")

        intent = router.route(state, "查订单 A1001")

        self.assertEqual(intent.main_intent, "order_query")
        self.assertEqual(intent.slots["order_id"], "A1001")
        self.assertFalse(intent.needs_clarification)

    def test_intent_router_should_detect_after_sale_refund(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s5", user_id="u1", channel="web")

        intent = router.route(state, "我要退款")

        self.assertEqual(intent.main_intent, "after_sale_refund")
        self.assertEqual(intent.sub_intent, "after_sale_refund.request_refund")

    def test_intent_router_should_detect_greeting(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s6", user_id="u1", channel="web")

        intent = router.route(state, "hello")

        self.assertEqual(intent.main_intent, "chitchat")
        self.assertEqual(intent.sub_intent, "chitchat.greeting")

    def test_intent_router_should_fall_to_unrecognize(self) -> None:
        router = IntentRouterService(llm_fallback_service=None)
        state = ConversationState(session_id="s7", user_id="u1", channel="web")

        intent = router.route(state, "asdfgh")

        self.assertEqual(intent.main_intent, "unrecognize")
        self.assertTrue(intent.needs_clarification)

    def test_intent_router_should_reject_unsupported_biz(self) -> None:
        # 规则不命中，LLM 兜底返回 unsupported_biz
        mock_llm = unittest.mock.MagicMock()
        mock_llm.enabled = True
        mock_llm.classify.return_value = IntentResult(
            main_intent="unsupported_biz",
            sub_intent="unsupported_biz.out_of_scope",
            confidence=0.85,
            route_source="llm_fallback",
        )
        router = IntentRouterService(llm_fallback_service=mock_llm)
        state = ConversationState(session_id="s8", user_id="u1", channel="web")

        intent = router.route(state, "你们招人吗")

        self.assertEqual(intent.main_intent, "unsupported_biz")

    def test_state_tracker_should_archive_previous_intent_and_inherit_slots(self) -> None:
        tracker = StateTrackerService(schema_registry=IntentSchemaRegistry())
        state = ConversationState(
            session_id="s9",
            user_id="u1",
            channel="web",
            current_main_intent="logistics",
            current_sub_intent="logistics.not_received",
            stage="done",
            slots={"order_id": "A1001"},
            summary="用户已查询物流",
        )
        intent = IntentResult(
            main_intent="after_sale_refund",
            sub_intent="after_sale_refund.request_refund",
            confidence=0.9,
            is_intent_shift=True,
        )

        updated = tracker.apply(state, intent)

        self.assertEqual(updated.current_main_intent, "after_sale_refund")
        self.assertEqual(updated.slots["order_id"], "A1001")
        self.assertTrue(updated.archived_states)
        self.assertEqual(updated.archived_states[-1]["main_intent"], "logistics")

    def test_policy_should_handoff_after_repeated_slot_clarification(self) -> None:
        policy = HandoffClarificationPolicy()
        state = ConversationState(
            session_id="s10",
            user_id="u1",
            channel="web",
            current_main_intent="order_query",
            current_sub_intent="order_query.query_status",
            missing_slots=["order_id"],
            needs_clarification=True,
            slot_clarification_count=3,
        )

        updated = policy.decide(state)

        self.assertEqual(updated.current_action, "handoff_human")
        self.assertTrue(updated.handoff)
        self.assertEqual(updated.handoff_reason, "clarification_failed")

    def test_policy_should_set_answer_directly_for_complaint(self) -> None:
        policy = HandoffClarificationPolicy()
        state = ConversationState(
            session_id="s11",
            user_id="u1",
            channel="web",
            current_main_intent="complaint",
            current_sub_intent="complaint.service_complaint",
            emotion={"primary": "angry", "confidence": 0.9, "trend": "escalating"},
        )

        updated = policy.decide(state)

        self.assertEqual(updated.current_action, "answer_directly")


if __name__ == "__main__":
    unittest.main()
