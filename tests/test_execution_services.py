import unittest

from app.schema import ConversationState
from app.business import HandoffService, LogisticsService, OrderService
from app.business.execution import ExecutionService


class ExecutionServicesTestCase(unittest.TestCase):
    def test_execution_service_should_query_order_tool(self) -> None:
        service = ExecutionService(
            order_service=OrderService(),
            logistics_service=LogisticsService(),
            handoff_service=HandoffService(),
        )
        state = ConversationState(
            session_id="s2",
            user_id="u1",
            channel="web",
            current_sub_intent="order_query.query_status",
            slots={"order_id": "A1001"},
        )

        updated = service.execute_business_tool(state)

        self.assertEqual(updated.tool_result.kind, "order_query")
        self.assertEqual(updated.tool_result.sanitized_result["order_id"], "A1001")

    def test_execution_service_should_create_handoff_ticket(self) -> None:
        service = ExecutionService(
            order_service=OrderService(),
            logistics_service=LogisticsService(),
            handoff_service=HandoffService(),
        )
        state = ConversationState(
            session_id="s3",
            user_id="u1",
            channel="web",
            summary="需要人工处理",
        )

        updated = service.create_handoff(state)

        self.assertEqual(updated.tool_result.kind, "handoff")
        self.assertTrue(updated.handoff)


if __name__ == "__main__":
    unittest.main()
