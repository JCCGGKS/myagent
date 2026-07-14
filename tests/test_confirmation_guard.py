"""confirmation_guard 节点端到端验证（真实图节点 + 真实 ToolExecutor 退款路径）。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.business.agent import CustomerServiceAgent
from app.business.tools.domain import RefundService
from app.schema import ChatRequest, ConversationState


def _make_agent():
    store = AsyncMock()
    llm_client = AsyncMock()
    message = MagicMock(content="LLM 回复", tool_calls=None)
    llm_client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=message)])
    agent = CustomerServiceAgent(
        store=store,
        order_service=MagicMock(),
        logistics_service=MagicMock(),
        handoff_service=MagicMock(),
        llm_client=llm_client,
        llm_model="fake-model",
    )
    # 订单状态「待付款」命中自动退款路径（AUTO_REFUNDABLE_STATUSES 默认含 待付款/待发货）
    agent.tool_executor.order_service.get_order_status.return_value = MagicMock(status="待付款")
    agent.tool_executor.refund_service = RefundService()
    return agent


def _state_with_pending(message: str) -> ConversationState:
    state = ConversationState(session_id="s", user_id=1, channel="web")
    state.pending_confirmation = {
        "tool": "request_refund",
        "order_id": "A1002",
        "refund_type": "refund",
        "reason": "",
    }
    state.recent_messages = [{"role": "user", "content": message}]
    return state


class TestConfirmationGuard:
    def test_confirm_replay_executes_refund(self):
        """用户回「确认」→ guard 以 confirm=true 重放，真正发起退款并清空挂起态。"""
        agent = _make_agent()
        state = _state_with_pending("确认")
        payload = {"state": state, "request": ChatRequest(session_id="s", message="确认")}
        asyncio.run(agent.confirmation_guard(payload))

        assert state.pending_confirmation is None
        assert state.tool_result is not None
        assert state.tool_result.kind == "success"
        assert state.tool_result.sanitized_result["order_id"] == "A1002"
        assert state.tool_result.sanitized_result["refund_id"].startswith("R")

    def test_cancel_clears_pending_and_replies(self):
        """用户回「取消」→ 清空挂起态并直接给取消话术，不再发起退款。"""
        agent = _make_agent()
        state = _state_with_pending("取消")
        payload = {"state": state, "request": ChatRequest(session_id="s", message="取消")}
        asyncio.run(agent.confirmation_guard(payload))

        assert state.pending_confirmation is None
        assert state.tool_result is None
        assert state.reply  # 取消话术非空

    def test_no_pending_passes_through(self):
        """无挂起确认时，guard 透传、不改动状态。"""
        agent = _make_agent()
        state = ConversationState(session_id="s", user_id=1, channel="web")
        state.recent_messages = [{"role": "user", "content": "你好"}]
        payload = {"state": state, "request": ChatRequest(session_id="s", message="你好")}
        asyncio.run(agent.confirmation_guard(payload))

        assert state.pending_confirmation is None
        assert state.reply == ""
        assert state.tool_result is None
