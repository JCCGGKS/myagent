"""测试 ToolExecutor（统一工具执行服务，直接驱动 domain 服务）。"""

import asyncio
import json
from unittest.mock import MagicMock

from app.business.tools.domain import HandoffService, OrderService, RefundService
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
        messages = asyncio.run(executor.run(tool_calls, state))

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
        asyncio.run(executor.run(tool_calls, state))

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
        asyncio.run(executor.run(tool_calls, state))

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
        asyncio.run(executor.run(tool_calls, state))
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
        messages = asyncio.run(executor.run(tool_calls, state))

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

    def test_run_request_refund_needs_confirmation_first(self):
        """R1 二次确认：未确认（无 confirm=true）时只返回确认提示，绝不真正发起退款。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        refund_service = RefundService()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=refund_service,
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
        messages = asyncio.run(executor.run(tool_calls, state))

        # 返回 confirmation 型结果，且未真正办理（计数器未动，受理单未生成）
        assert state.tool_result is not None
        assert state.tool_result.kind == "confirmation"
        assert "确认" in state.tool_result.user_facing_summary
        assert state.reply
        assert "确认" in state.reply
        # 确认提示直达用户（response_generator 早返回），同时作为 tool 消息回灌 LLM
        assert json.loads(messages[0]["content"])["kind"] == "confirmation"
        # 服务层未发起任何退款
        assert refund_service._by_key == {}

    def test_run_request_refund_with_confirm_executes(self):
        """R1 二次确认：用户确认后模型以 confirm=true 二次调用，才真正发起退款。"""
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
                "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund", "confirm": true}'},
            }
        ]
        state = _state()
        asyncio.run(executor.run(tool_calls, state))

        assert state.tool_result is not None
        assert state.tool_result.kind == "aftersale_refund"
        assert state.tool_result.sanitized_result["order_id"] == "A1001"
        assert state.tool_result.sanitized_result["refund_id"].startswith("R")
        # 确认痕迹写入审计字段
        assert "refund:A1001:refund" in state.confirmed_slots

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
        asyncio.run(executor.run(tool_calls, state))

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
        asyncio.run(executor.run(tool_calls, state))

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
        asyncio.run(executor.run(tool_calls, state))

        assert state.tool_result is not None
        assert state.tool_result.kind == "order_query"
        assert state.tool_result.sanitized_result["invoice_title"] == "XX公司"

    def test_run_failure_isolation_continues_batch(self):
        """R6 失败隔离：某个工具处理器抛异常时，run() 不应向上抛出、也不应中断整批。

        - 异常工具被转成 error 型 tool_result 回灌（LLM 能收到 observation）；
        - 同一批里其余工具继续正常执行；
        - 指标照常记录（不崩溃）。
        """
        rag_tool = MagicMock()
        rag_tool.run.return_value = []

        exploding = MagicMock()
        exploding.side_effect = RuntimeError("boom")

        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        executor.retry_base_delay = 0
        executor.retry_max_delay = 0
        # 注入一个会抛异常的处理器
        executor._handlers["query_order"] = exploding

        tool_calls = [
            {
                "id": "call_a",
                "type": "function",
                "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'},
            },
            {
                "id": "call_b",
                "type": "function",
                "function": {"name": "rag_retrieve", "arguments": '{"query": "退货政策"}'},
            },
        ]
        state = _state()

        # 不应抛异常
        messages = asyncio.run(executor.run(tool_calls, state))

        # 两个工具都产出 tool 消息（批未中断）
        assert len(messages) == 2
        # 第一个（异常）转为 error 型 tool_result
        failed = [m for m in messages if m["tool_call_id"] == "call_a"][0]

        assert json.loads(failed["content"])["kind"] == "error"
        # 第二个（正常）照常执行
        ok = [m for m in messages if m["tool_call_id"] == "call_b"][0]
        assert json.loads(ok["content"])["kind"] == "knowledge"
        # 指标未崩溃（last_result 落为 error，因为异常工具在最后被处理？此处批末是 rag，故 last 为 knowledge）
        assert state.tool_result is not None

    def test_run_retries_transient_failure_then_succeeds(self):
        """失败重试：非副作用工具基础设施故障，重试后成功则不返回 error。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        success = ToolExecutionResult(kind="order_query", user_facing_summary="ok")
        # 前两次抛异常，第三次成功
        flaky = MagicMock(side_effect=[RuntimeError("t1"), RuntimeError("t2"), success])

        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        executor.retry_base_delay = 0
        executor.retry_max_delay = 0
        executor._handlers["query_order"] = flaky  # query_order 是只读，可重试

        tool_calls = [
            {
                "id": "call_r",
                "type": "function",
                "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'},
            }
        ]
        state = _state()
        messages = asyncio.run(executor.run(tool_calls, state))

        # 共尝试 3 次（1 + max_retries=2）
        assert flaky.call_count == 3
        assert json.loads(messages[0]["content"])["kind"] == "order_query"
        assert state.tool_result.kind == "order_query"

    def test_run_side_effect_tool_not_retried(self):
        """副作用工具（request_refund）失败不自动重试，避免重复触发不可逆动作。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        boom = MagicMock(side_effect=RuntimeError("boom"))

        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        executor.retry_base_delay = 0
        executor._handlers["request_refund"] = boom  # request_refund 是副作用工具

        tool_calls = [
            {
                "id": "call_s",
                "type": "function",
                "function": {"name": "request_refund", "arguments": '{"order_id": "A1001"}'},
            }
        ]
        state = _state()
        messages = asyncio.run(executor.run(tool_calls, state))

        # 只调用 1 次（不重试）
        assert boom.call_count == 1
        assert json.loads(messages[0]["content"])["kind"] == "error"
        assert state.tool_result.kind == "error"

    def test_refund_idempotent_same_order_and_type(self):
        """R2 幂等：同一 (订单号, 退款类型) 重复请求返回同一受理单，不会生成新单号。"""
        svc = RefundService()
        first = svc.request_refund("A1001", refund_type="refund", reason="不想要了")
        second = svc.request_refund("A1001", refund_type="refund")
        assert first.refund_id == second.refund_id
        # 不同退款类型应视为不同受理单
        third = svc.request_refund("A1001", refund_type="return")
        assert third.refund_id != first.refund_id

    def test_handoff_idempotent_same_session(self):
        """R2 幂等：同一会话重复转人工返回同一服务单，不会重复建单。"""
        svc = HandoffService()
        first = svc.create_handoff("session-1", "投诉")
        second = svc.create_handoff("session-1", "投诉升级")
        assert first.ticket_id == second.ticket_id
        # 不同会话仍是不同单
        third = svc.create_handoff("session-2", "咨询")
        assert third.ticket_id != first.ticket_id

    def test_run_refund_confirmed_twice_idempotent(self):
        """R2 兜底：用户确认后即便模型重复以 confirm=true 调用，也不会生成多个受理单。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        call = {
            "id": "call_confirm",
            "type": "function",
            "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund", "confirm": true}'},
        }
        state = _state()
        asyncio.run(executor.run([call], state))
        first_id = state.tool_result.sanitized_result["refund_id"]
        # 同一 state（已带 confirmed_slots）下再次确认调用
        asyncio.run(executor.run([call], state))
        second_id = state.tool_result.sanitized_result["refund_id"]
        assert first_id == second_id
