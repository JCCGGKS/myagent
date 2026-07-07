import unittest

from app.models import ConversationState, IntentResult
from app.rag import KnowledgeBaseService
from app.services.intent_schema import IntentRuleRegistry, IntentSchemaRegistry
from app.services.routing import (
    HandoffClarificationPolicy,
    IntentRouterService,
    StateTrackerService,
)


class RoutingServicesTestCase(unittest.TestCase):
    def test_intent_schema_registry_should_load_default_yaml_schema(self) -> None:
        registry = IntentSchemaRegistry()

        schema = registry.get("refund_service")

        self.assertEqual(schema["required_slots"], ["order_id"])
        self.assertIn("refund_reason", schema["optional_slots"])

    def test_intent_rule_registry_should_load_default_yaml_rules(self) -> None:
        registry = IntentRuleRegistry()

        rules = registry.get()

        self.assertIn("handoff_keywords", rules)
        self.assertIn("转人工", rules["handoff_keywords"])

    def test_intent_router_should_detect_refund_faq_and_emotion(self) -> None:
        router = IntentRouterService(knowledge_base=KnowledgeBaseService(), llm_fallback_service=None)
        state = ConversationState(session_id="s1", user_id="u1", channel="web")

        intent = router.route(state, "退款多久到账")

        self.assertEqual(intent.main_intent, "refund_service")
        self.assertEqual(intent.sub_intent, "refund_service.consult_policy")
        self.assertEqual(intent.emotion.primary, "neutral")

    def test_intent_router_should_detect_handoff_and_greeting_from_yaml_rules(self) -> None:
        router = IntentRouterService(knowledge_base=KnowledgeBaseService(), llm_fallback_service=None)
        state = ConversationState(session_id="s1b", user_id="u1", channel="web")

        handoff_intent = router.route(state, "我要转人工")
        greeting_intent = router.route(state, "hello")

        self.assertEqual(handoff_intent.main_intent, "handoff_service")
        self.assertEqual(greeting_intent.sub_intent, "chitchat.greeting")

    def test_state_tracker_should_archive_previous_intent_and_inherit_slots(self) -> None:
        tracker = StateTrackerService(schema_registry=IntentSchemaRegistry())
        state = ConversationState(
            session_id="s2",
            user_id="u1",
            channel="web",
            current_main_intent="logistics_service",
            current_sub_intent="logistics_service.query_status",
            stage="done",
            slots={"order_id": "A1001"},
            summary="用户已查询物流",
        )
        intent = IntentResult(
            main_intent="refund_service",
            sub_intent="refund_service.request_refund",
            confidence=0.9,
            is_intent_shift=True,
        )

        updated = tracker.apply(state, intent)

        self.assertEqual(updated.current_main_intent, "refund_service")
        self.assertEqual(updated.slots["order_id"], "A1001")
        self.assertTrue(updated.archived_states)
        self.assertEqual(updated.archived_states[-1]["main_intent"], "logistics_service")

    def test_policy_should_handoff_after_repeated_slot_clarification(self) -> None:
        policy = HandoffClarificationPolicy()
        state = ConversationState(
            session_id="s3",
            user_id="u1",
            channel="web",
            current_main_intent="order_service",
            current_sub_intent="order_service.query_status",
            missing_slots=["order_id"],
            needs_clarification=True,
            slot_clarification_count=3,
        )

        updated = policy.decide(state)

        self.assertEqual(updated.current_action, "handoff_human")
        self.assertTrue(updated.handoff)
        self.assertEqual(updated.handoff_reason, "clarification_failed")


if __name__ == "__main__":
    unittest.main()
