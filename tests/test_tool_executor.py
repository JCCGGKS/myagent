"""测试 ToolExecutor（统一工具执行服务，直接驱动 domain 服务）。"""

from unittest.mock import MagicMock

from app.business.tools.domain import OrderService, RefundService
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

    def test_run_create_handoff_serializes_without_state_error(self):
        """回归：create_handoff 经 run() 调用时，工具消息内容必须是可 JSON 序列化的
        ToolExecutionResult，不能是整份 ConversationState（否则 json.dumps 报
        'Object of type ConversationState is not JSON serializable'）。"""
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
                "id": "call_5",
                "type": "function",
                "function": {"name": "create_handoff", "arguments": "{}"},
            }
        ]
        state = _state(summary="需要人工处理")
        messages = executor.run(tool_calls, state)

        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        # 关键：内容可被标准 json 序列化（不再整段塞入 ConversationState）
        import json

        parsed = json.loads(messages[0]["content"])
        assert parsed["kind"] == "handoff"
        assert state.tool_result is not None
        assert state.tool_result.kind == "handoff"

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

    def test_create_handoff_writes_reply_to_skip_redundant_llm(self):
        """create_handoff 应直接写 state.reply，使 response_generator 命中早返回、不再调 LLM。"""
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

        assert updated.reply
        assert "T-001" in updated.reply
        # reply 非空 → response_generator 会直接 return，不触发额外 LLM 调用
        assert updated.handoff is True

    def test_run_request_refund_returns_aftersale_result(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {
                "id": "call_r1",
                "type": "function",
                "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund"}'},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        assert state.tool_result is not None
        assert state.tool_result.kind == "aftersale_refund"
        assert state.tool_result.sanitized_result["order_id"] == "A1001"
        assert state.tool_result.sanitized_result["refund_id"].startswith("R")

    def test_request_refund_missing_order_id_errors(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {
                "id": "call_r2",
                "type": "function",
                "function": {"name": "request_refund", "arguments": "{}"},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        assert state.tool_result is not None
        assert state.tool_result.kind == "error"

    def test_run_modify_address_uses_order_service(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=OrderService(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {
                "id": "call_m1",
                "type": "function",
                "function": {"name": "modify_address", "arguments": '{"order_id": "A1001", "new_address": "北京市朝阳区"}'},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        assert state.tool_result is not None
        assert state.tool_result.kind == "order_query"
        assert state.tool_result.sanitized_result["new_address"] == "北京市朝阳区"

    def test_run_apply_invoice_uses_order_service(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=OrderService(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {
                "id": "call_i1",
                "type": "function",
                "function": {"name": "apply_invoice", "arguments": '{"order_id": "A1001", "invoice_title": "XX公司"}'},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        assert state.tool_result is not None
        assert state.tool_result.kind == "order_query"
        assert state.tool_result.sanitized_result["invoice_title"] == "XX公司"
