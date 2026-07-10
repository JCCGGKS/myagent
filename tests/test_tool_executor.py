"""测试 ToolExecutor（统一工具执行服务）。"""

from unittest.mock import MagicMock

from app.schema import ConversationState, ToolExecutionResult
from app.business.tool_executor import ToolExecutor


def _state():
    return ConversationState(session_id="test-session", user_id=1, channel="web")


def _fake_execution_service():
    svc = MagicMock()
    svc.run_tool.return_value = ToolExecutionResult(
        kind="order_query",
        raw_result={"order_id": "A1001", "status": "已发货"},
        sanitized_result={"order_id": "A1001", "status": "已发货"},
        user_facing_summary="订单 A1001 当前状态为 已发货",
    )
    return svc


class TestToolExecutor:
    def test_run_query_order_sets_tool_result_and_messages(self):
        exec_svc = _fake_execution_service()
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(execution_service=exec_svc, rag_tool=rag_tool)

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
        exec_svc.run_tool.assert_called_once_with("query_order", {"order_id": "A1001"}, state)

    def test_run_rag_retrieve_uses_rag_tool(self):
        rag_tool = MagicMock()
        rag_tool.run.return_value = [{"content": "政策片段", "score": 0.9}]
        executor = ToolExecutor(execution_service=_fake_execution_service(), rag_tool=rag_tool)

        tool_calls = [
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "rag_retrieve", "arguments": '{"query": "退货政策"}'},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)

        rag_tool.run.assert_called_once_with("退货政策", user_id=1)
        assert state.tool_result.kind == "knowledge"

    def test_run_unknown_tool_returns_error_result(self):
        # 无 execution_service 时，未知工具直接返回 error 结果
        executor = ToolExecutor(execution_service=None)
        tool_calls = [
            {
                "id": "call_3",
                "type": "function",
                "function": {"name": "unknown_tool", "arguments": "{}"},
            }
        ]
        state = _state()
        executor.run(tool_calls, state)
        assert state.tool_result is not None
        assert state.tool_result.kind == "error"
