import unittest

from app.models import ChatRequest, ConversationState, ToolExecutionResult
from app.services.dialog import ClarificationService, MemoryService, ResponseService
from app.store import SessionStore


class DialogServicesTestCase(unittest.TestCase):
    def test_clarification_service_should_generate_refund_order_id_prompt(self) -> None:
        service = ClarificationService()
        state = ConversationState(
            session_id="s1",
            user_id="u1",
            channel="web",
            current_main_intent="refund_service",
            current_sub_intent="refund_service.request_refund",
            current_action="ask_slot_clarification",
            missing_slots=["order_id"],
        )

        updated = service.generate(state)

        self.assertIn("订单号", updated.reply)
        self.assertEqual(updated.latest_action_name, "clarification_node")

    def test_response_service_should_render_order_reply_from_tool_result(self) -> None:
        service = ResponseService()
        state = ConversationState(
            session_id="s2",
            user_id="u1",
            channel="web",
            current_main_intent="order_service",
            current_sub_intent="order_service.query_status",
            tool_result=ToolExecutionResult(
                kind="order",
                raw_result=None,
                sanitized_result={
                    "order_id": "A1001",
                    "status": "PAID",
                    "product_name": "卫衣",
                    "amount": 199.0,
                },
                user_facing_summary="订单 A1001 当前状态为 PAID",
            ),
        )

        updated = service.generate(state)

        self.assertIn("订单 A1001 当前状态为 PAID", updated.reply)

    def test_memory_service_should_record_messages_and_tool_calls(self) -> None:
        store = SessionStore()
        service = MemoryService(store=store)
        state = ConversationState(
            session_id="s3",
            user_id="u1",
            channel="web",
            current_main_intent="faq",
            current_sub_intent="faq.general",
            current_action="retrieve_knowledge",
            reply="退款到账时间通常为 1 到 5 个工作日。",
            tool_result=ToolExecutionResult(
                kind="knowledge",
                raw_result={"hits": []},
                sanitized_result={"faq_key": "退款多久到账"},
                user_facing_summary="退款到账时间通常为 1 到 5 个工作日。",
            ),
        )
        request = ChatRequest(session_id="s3", user_id="u1", channel="web", message="退款多久到账")

        service.persist(state, request)

        record = store.dump_session_record("s3")
        self.assertIsNotNone(record)
        self.assertEqual(len(record["messages"]), 2)
        self.assertEqual(len(record["tool_calls"]), 1)


if __name__ == "__main__":
    unittest.main()
