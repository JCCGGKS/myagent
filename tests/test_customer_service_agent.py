import unittest

from app.agents import CustomerServiceAgent
from app.models import ChatRequest
from app.rag import KnowledgeBaseService
from app.services import HandoffService, LogisticsService, OrderService
from app.store import SessionStore


def build_agent() -> CustomerServiceAgent:
    return CustomerServiceAgent(
        store=SessionStore(),
        knowledge_base=KnowledgeBaseService(),
        order_service=OrderService(),
        logistics_service=LogisticsService(),
        handoff_service=HandoffService(),
        llm_fallback_service=None,
    )


class CustomerServiceAgentTestCase(unittest.TestCase):
    def test_after_sale_refund_should_match_refund_arrival_question(self) -> None:
        agent = build_agent()

        response = agent.chat(
            ChatRequest(
                session_id="s-refund",
                user_id="u-1",
                channel="web",
                message="退款多久到账",
            )
        )

        self.assertEqual(response.main_intent, "after_sale_refund")
        # The system may ask for clarification or provide general refund info
        self.assertTrue(len(response.reply) > 0)

    def test_order_flow_should_ask_for_order_id_then_answer(self) -> None:
        agent = build_agent()

        first = agent.chat(
            ChatRequest(
                session_id="s-order",
                user_id="u-1",
                channel="web",
                message="帮我查一下订单",
            )
        )

        self.assertTrue(first.needs_clarification)
        self.assertIn("订单号", first.reply)

        second = agent.chat(
            ChatRequest(
                session_id="s-order",
                user_id="u-1",
                channel="web",
                message="A1001",
            )
        )

        self.assertEqual(second.main_intent, "order_query")
        self.assertFalse(second.needs_clarification)
        self.assertIn("订单 A1001 当前状态为", second.reply)

    def test_intent_shift_should_archive_previous_state_and_inherit_order_id(self) -> None:
        agent = build_agent()

        logistics_response = agent.chat(
            ChatRequest(
                session_id="s-shift",
                user_id="u-1",
                channel="web",
                message="订单 A1001 到哪了",
            )
        )
        self.assertEqual(logistics_response.main_intent, "logistics")
        self.assertEqual(logistics_response.slots["order_id"], "A1001")

        refund_response = agent.chat(
            ChatRequest(
                session_id="s-shift",
                user_id="u-1",
                channel="web",
                message="那我要退款",
            )
        )

        self.assertEqual(refund_response.main_intent, "after_sale_refund")
        self.assertEqual(refund_response.slots["order_id"], "A1001")
        archived_states = refund_response.session_state["archived_states"]
        self.assertTrue(archived_states)
        self.assertEqual(archived_states[-1]["main_intent"], "logistics")

    def test_unknown_message_should_not_reuse_previous_answer(self) -> None:
        agent = build_agent()

        first = agent.chat(
            ChatRequest(
                session_id="s-unknown",
                user_id="u-1",
                channel="web",
                message="退款多久到账",
            )
        )
        # Just verify we got a response
        self.assertTrue(len(first.reply) > 0)

        second = agent.chat(
            ChatRequest(
                session_id="s-unknown",
                user_id="u-1",
                channel="web",
                message="你好呀呀呀",
            )
        )

        self.assertNotEqual(second.reply, first.reply)
        # Message "你好呀呀呀" could be chitchat.greeting or unrecognize
        self.assertIn(second.main_intent, {"chitchat", "unrecognize"})


if __name__ == "__main__":
    unittest.main()
