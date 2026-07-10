"""测试 ToolExecutor（统一工具执行服务，直接驱动 domain 服务）。"""

from unittest.mock import MagicMock

from app.schema import (
    ConversationState,
    HandoffResult,
    LogisticsEvent,
    LogisticsInfo,
    OrderInfo,
    ToolExecutionResult,
)
from app.business.tools.tool_executor import ToolExecutor


def _state(summary: str = "") -> ConversationState:
    return ConversationState(
        session_id="test-session",
        user_id=1,
        channel="web",
        summary=summary,
    )


def _fake_order_service() -> MagicMock:
    svc = MagicMock()
    svc.get_order_status.return_value = OrderInfo(
        order_id="A1001", status="已发货", product_name="键盘", amount=199.0
    )
    return svc


def _fake_logistics_service() -> MagicMock:
    svc = MagicMock()
    svc.get_logistics.return_value = LogisticsInfo(
        order_id="A1001",
        tracking_status="运输中",
        timeline=[LogisticsEvent(time="10:00", status="已揽收")],
    )
    return svc


def _fake_handoff_service() -> MagicMock:
    svc = MagicMock()
    svc.create_handoff.return_value = HandoffResult(ticket_id="T-001", summary="需要人工处理")
    return svc


class TestToolExecutor:
    def test_run_query_order_sets_tool_result_and_messages(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            rag_tool=rag_tool,
        )

        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'},
            }
        ]
        state = _state()
        messages = executor.run(tool_calls, state)

        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_1"
        assert messages[0]["name"] == "query_order"
        assert state.tool_result is not None
        assert state.tool_result.kind == "order_query"
        assert state.tool_result.sanitized_result["order_id"] == "A1001"

    def test_run_logistics_sets_logistics_result(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            rag_tool=rag_tool,
        )

        tool_calls = [
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "query_logistics", "arguments": '{"order_id": "A1001"}'},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        assert state.tool_result is not None
        assert state.tool_result.kind == "logistics"
        assert state.tool_result.sanitized_result["tracking_status"] == "运输中"

    def test_run_rag_retrieve_uses_rag_tool(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = [{"content": "政策片段", "score": 0.9}]
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            rag_tool=rag_tool,
        )

        tool_calls = [
            {
                "id": "call_3",
                "type": "function",
                "function": {"name": "rag_retrieve", "arguments": '{"query": "退货政策"}'},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        rag_tool.run.assert_called_once_with("退货政策", user_id=1)
        assert state.tool_result.kind == "knowledge"

    def test_run_unknown_tool_returns_error_result(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {
                "id": "call_4",
                "type": "function",
                "function": {"name": "unknown_tool", "arguments": "{}"},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)
        assert state.tool_result is not None
        assert state.tool_result.kind == "error"

    def test_create_handoff_sets_handoff_state(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            rag_tool=rag_tool,
        )
        state = _state(summary="需要人工处理")

        updated = executor.create_handoff(state)

        assert updated.tool_result.kind == "handoff"
        assert updated.handoff is True
        assert updated.tool_result.sanitized_result["ticket_id"] == "T-001"
