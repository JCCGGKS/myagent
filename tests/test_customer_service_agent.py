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
    def test_faq_answer_should_match_refund_arrival_question(self) -> None:
        agent = build_agent()

        response = agent.chat(
            ChatRequest(
                session_id="s-faq",
                user_id="u-1",
                channel="web",
                message="退款多久到账",
            )
        )

        self.assertIn(response.main_intent, {"faq", "refund_service"})
        self.assertIn("1 到 5 个工作日", response.reply)

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

        self.assertEqual(second.main_intent, "order_service")
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
        self.assertEqual(logistics_response.main_intent, "logistics_service")
        self.assertEqual(logistics_response.slots["order_id"], "A1001")

        refund_response = agent.chat(
            ChatRequest(
                session_id="s-shift",
                user_id="u-1",
                channel="web",
                message="那我要退款",
            )
        )

        self.assertEqual(refund_response.main_intent, "refund_service")
        self.assertEqual(refund_response.slots["order_id"], "A1001")
        archived_states = refund_response.session_state["archived_states"]
        self.assertTrue(archived_states)
        self.assertEqual(archived_states[-1]["main_intent"], "logistics_service")

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
        self.assertIn("1 到 5 个工作日", first.reply)

        second = agent.chat(
            ChatRequest(
                session_id="s-unknown",
                user_id="u-1",
                channel="web",
                message="你好呀呀呀",
            )
        )

        self.assertNotEqual(second.reply, first.reply)
        self.assertIn(second.main_intent, {"chitchat", "unsupported"})


if __name__ == "__main__":
    unittest.main()
