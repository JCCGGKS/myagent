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
        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "query_order"
        assert state.tool_results[-1].kind == "success"
        assert state.tool_results[-1].sanitized_result["order_id"] == "A1001"

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

        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "query_logistics"
        assert state.tool_results[-1].kind == "success"
        assert state.tool_results[-1].sanitized_result["tracking_status"] == "运输中"

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
        assert state.tool_results[-1].tool == "rag_retrieve"
        assert state.tool_results[-1].kind == "success"

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
        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].kind == "error"

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
        assert parsed["tool"] == "create_handoff"
        assert parsed["kind"] == "handoff"
        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "create_handoff"
        assert state.tool_results[-1].kind == "handoff"

    def test_run_multiple_tool_calls_accumulate_all_results(self):
        """数组化回归：一次 run 传入多个 tool_calls 时，全部结果累积进
        ``state.tool_results``，互不覆盖（修复「多工具只保留最后一个」的 bug）。"""
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
                "id": "call_o",
                "type": "function",
                "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'},
            },
            {
                "id": "call_l",
                "type": "function",
                "function": {"name": "query_logistics", "arguments": '{"order_id": "A1001"}'},
            },
        ]
        state = _state()
        messages = asyncio.run(executor.run(tool_calls, state))

        assert len(messages) == 2
        assert len(state.tool_results) == 2
        tools = {r.tool for r in state.tool_results}
        assert tools == {"query_order", "query_logistics"}

    def test_create_handoff_sets_handoff_state(self):
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
                "id": "call_h",
                "type": "function",
                "function": {"name": "create_handoff", "arguments": "{}"},
            }
        ]
        state = _state(summary="需要人工处理")
        asyncio.run(executor.run(tool_calls, state))

        assert state.tool_results[-1].tool == "create_handoff"
        assert state.tool_results[-1].kind == "handoff"
        assert state.handoff is True
        assert state.tool_results[-1].sanitized_result["ticket_id"] == "T-001"

    def test_create_handoff_does_not_write_reply_decision_only(self):
        """决策层（create_handoff）只产 tool_result + 状态标志，绝不直接写 state.reply；
        回复由 response_generator 按 yml 模板统一生成。"""
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
                "id": "call_h",
                "type": "function",
                "function": {"name": "create_handoff", "arguments": "{}"},
            }
        ]
        state = _state(summary="需要人工处理")
        asyncio.run(executor.run(tool_calls, state))

        assert state.tool_results[-1].tool == "create_handoff"
        assert state.tool_results[-1].kind == "handoff"
        assert state.handoff is True
        assert state.tool_results[-1].sanitized_result["ticket_id"] == "T-001"
        # 决策层不写回复 → 交由生成节点按 yml 模板产出
        assert state.reply == ""

    def test_run_request_refund_needs_confirmation_first(self):
        """R1 二次确认：未确认（无 confirm=true）时只返回确认提示，绝不真正发起退款。

        注：订单 A1001 状态为「已发货」，需经 refund_auto_states={"已发货"} 切回自动退款
        路径，才能命中 R1 确认分支（否则默认走阶段一的「建申请单+转人工」分支）。
        """
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        refund_service = RefundService()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=refund_service,
            rag_tool=rag_tool,
            refund_auto_states={"已发货"},
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
        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "request_refund"
        assert state.tool_results[-1].kind == "confirmation"
        # 决策层不写回复，确认话术由生成节点按 yml 模板产出（数据在 raw_result 中）
        assert state.reply == ""
        assert state.tool_results[-1].raw_result["order_id"] == "A1001"
        # R1 挂起态：发出确认时记录待确认负载，供下一轮「确认」信号确定性拦截
        assert state.pending_confirmation == {
            "tool": "request_refund",
            "order_id": "A1001",
            "refund_type": "refund",
            "reason": "",
        }
        # 同时作为 tool 消息回灌 LLM
        assert json.loads(messages[0]["content"])["kind"] == "confirmation"
        # 服务层未发起任何退款
        assert refund_service._by_key == {}

    def test_request_refund_auto_pending_lifecycle(self):
        """R1 挂起态生命周期：首次（无 confirm）→ 挂起；用户「确认」后以 confirm=true
        重放 → 真正退款且挂起态清空。模拟 confirmation_guard 的确认分支。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        refund_service = RefundService()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=refund_service,
            rag_tool=rag_tool,
            refund_auto_states={"已发货"},
        )
        state = _state()
        # 首次：无 confirm → confirmation + 挂起
        first = [
            {"id": "c1", "type": "function",
             "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund"}'}},
        ]
        asyncio.run(executor.run(first, state))
        assert state.tool_results[-1].kind == "confirmation"
        assert state.pending_confirmation is not None
        assert refund_service._by_key == {}

        # 用户回「确认」→ guard 以 confirm=true 重放挂起负载
        replay = [
            {"id": "c2", "type": "function",
             "function": {"name": "request_refund",
                          "arguments": json.dumps({"order_id": "A1001", "refund_type": "refund", "confirm": True}, ensure_ascii=False)}},
        ]
        asyncio.run(executor.run(replay, state))
        assert state.tool_results[-1].kind == "success"
        assert state.tool_results[-1].sanitized_result["refund_id"].startswith("R")
        # 确认后挂起态清空，避免 stale
        assert state.pending_confirmation is None
        assert "refund:A1001:refund" in state.confirmed_slots

    def test_request_refund_auto_label_is_chinese(self):
        """refund_type 内部枚举（refund）在模板数据里应映射为中文标签，而非原样外泄。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
            refund_auto_states={"已发货"},
        )
        state = _state()
        calls = [
            {"id": "c", "type": "function",
             "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund"}'}},
        ]
        asyncio.run(executor.run(calls, state))
        assert state.tool_results[-1].raw_result["refund_type_label"] == "退款"
        # 成功分支同样带中文标签
        calls2 = [
            {"id": "c2", "type": "function",
             "function": {"name": "request_refund",
                          "arguments": json.dumps({"order_id": "A1001", "refund_type": "refund", "confirm": True}, ensure_ascii=False)}},
        ]
        asyncio.run(executor.run(calls2, state))
        assert state.tool_results[-1].raw_result["refund_type_label"] == "退款"

    def test_run_request_refund_with_confirm_executes(self):
        """R1 二次确认：用户确认后模型以 confirm=true 二次调用，才真正发起退款。

        同样需 refund_auto_states={"已发货"} 切回自动退款路径。
        """
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
            refund_auto_states={"已发货"},
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

        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "request_refund"
        assert state.tool_results[-1].kind == "success"
        assert state.tool_results[-1].sanitized_result["order_id"] == "A1001"
        assert state.tool_results[-1].sanitized_result["refund_id"].startswith("R")
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

        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].kind == "error"

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

        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "modify_address"
        assert state.tool_results[-1].kind == "success"
        # raw_result 含完整地址（未经脱敏）；sanitized_result 中地址字段按策略掩码
        assert state.tool_results[-1].raw_result["new_address"] == "北京市朝阳区"
        assert "****" in state.tool_results[-1].sanitized_result["new_address"]

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

        assert state.tool_results[-1] is not None
        assert state.tool_results[-1].tool == "apply_invoice"
        assert state.tool_results[-1].kind == "success"
        assert state.tool_results[-1].sanitized_result["invoice_title"] == "XX公司"

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
        assert json.loads(ok["content"])["kind"] == "success"
        # 指标未崩溃（last_result 落为 error，因为异常工具在最后被处理？此处批末是 rag，故 last 为 knowledge）
        assert state.tool_results[-1] is not None

    def test_run_retries_transient_failure_then_succeeds(self):
        """失败重试：非副作用工具基础设施故障，重试后成功则不返回 error。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        success = ToolExecutionResult(kind="success")
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
        assert json.loads(messages[0]["content"])["tool"] == "query_order"
        assert json.loads(messages[0]["content"])["kind"] == "success"
        assert state.tool_results[-1].tool == "query_order"
        assert state.tool_results[-1].kind == "success"

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
        assert state.tool_results[-1].kind == "error"

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
        """R2 兜底：用户确认后即便模型重复以 confirm=true 调用，也不会生成多个受理单。

        需 refund_auto_states={"已发货"} 切回自动退款路径，才能走 R2 幂等执行分支。
        """
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
            refund_auto_states={"已发货"},
        )
        call = {
            "id": "call_confirm",
            "type": "function",
            "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund", "confirm": true}'},
        }
        state = _state()
        asyncio.run(executor.run([call], state))
        first_id = state.tool_results[-1].sanitized_result["refund_id"]
        # 同一 state（已带 confirmed_slots）下再次确认调用
        asyncio.run(executor.run([call], state))
        second_id = state.tool_results[-1].sanitized_result["refund_id"]
        assert first_id == second_id

    def test_request_refund_in_transit_creates_handoff(self):
        """阶段一：不可自动退款的状态（如 已发货）不弹确认、不真退，而是建退款申请单 + 转人工。

        默认 ToolExecutor（refund_auto_states 为空）→ 所有状态走 handoff 分支。
        """
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        handoff_service = _fake_handoff_service()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=handoff_service,
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {
                "id": "call_h",
                "type": "function",
                "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund"}'},
            }
        ]
        state = _state()
        asyncio.run(executor.run(tool_calls, state))

        assert state.tool_results[-1].tool == "request_refund"
        assert state.tool_results[-1].kind == "handoff"
        # 决策层不写回复，话术由生成节点按 yml 模板产出
        assert state.reply == ""
        assert state.handoff is True
        handoff_service.create_handoff.assert_called_once()
        assert "handoff_ticket_id" in state.tool_results[-1].sanitized_result
        # 结果对象无 user_facing_summary 字段（已删除）
        assert not hasattr(state.tool_results[-1], "user_facing_summary")

    def test_request_refund_handoff_idempotent_same_session(self):
        """同会话重复「退掉」→ 同一服务单号（handoff 按 session_id 去重）。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        handoff_service = _fake_handoff_service()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=handoff_service,
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        call = {
            "id": "call_h2",
            "type": "function",
            "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "refund"}'},
        }
        state = _state()
        asyncio.run(executor.run([call], state))
        first_ticket = state.tool_results[-1].sanitized_result["handoff_ticket_id"]
        asyncio.run(executor.run([call], state))
        second_ticket = state.tool_results[-1].sanitized_result["handoff_ticket_id"]
        assert first_ticket == second_ticket

    def test_request_refund_unknown_order_errors(self):
        """订单不存在 → 返回 error（不建单、不转人工）。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        # 订单服务：仅 A1001 存在，其余（含 NOPE）返回 None
        order_service = MagicMock()

        def _get(oid: str):
            if oid == "A1001":
                return OrderInfo(order_id="A1001", status="已发货", product_name="键盘", amount=199.0)
            return None

        order_service.get_order_status.side_effect = _get
        executor = ToolExecutor(
            order_service=order_service,
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        call = {
            "id": "call_h3",
            "type": "function",
            "function": {"name": "request_refund", "arguments": '{"order_id": "NOPE", "refund_type": "refund"}'},
        }
        state = _state()
        asyncio.run(executor.run([call], state))
        assert state.tool_results[-1].tool == "request_refund"
        assert state.tool_results[-1].kind == "error"
        assert "NOPE" in state.tool_results[-1].raw_result["message"]

    # ---- R5 统一参数 schema 校验 ----

    def test_validate_tool_args_passes_valid(self):
        """R5：合法参数通过校验，返回 None。"""
        executor = ToolExecutor(refund_service=RefundService())
        err = executor._validate_tool_args(
            "request_refund", {"order_id": "A1001", "refund_type": "refund", "confirm": True}, _state()
        )
        assert err is None

    def test_validate_tool_args_missing_required(self):
        """R5：缺必填参数（order_id）被提前拦截。"""
        executor = ToolExecutor(refund_service=RefundService())
        err = executor._validate_tool_args("request_refund", {}, _state())
        assert err is not None
        assert "order_id" in err

    def test_validate_tool_args_wrong_type(self):
        """R5：类型错误（order_id 应为文本却传数字）被拦截。"""
        executor = ToolExecutor(refund_service=RefundService())
        err = executor._validate_tool_args("request_refund", {"order_id": 12345}, _state())
        assert err is not None
        assert "文本" in err

    def test_validate_tool_args_invalid_enum(self):
        """R5：枚举非法（refund_type=foo）被拦截。"""
        executor = ToolExecutor(refund_service=RefundService())
        err = executor._validate_tool_args(
            "request_refund", {"order_id": "A1001", "refund_type": "foo"}, _state()
        )
        assert err is not None
        assert "refund_type" in err

    def test_validate_tool_args_falls_back_to_slots(self):
        """R5：必填参数缺省时回退 state.slots 视为齐全（与 handler 取值一致）。"""
        executor = ToolExecutor(refund_service=RefundService())
        state = _state()
        state.slots = {"order_id": "A1001"}
        # 仅传 refund_type，order_id 由 slots 补
        err = executor._validate_tool_args("request_refund", {"refund_type": "refund"}, state)
        assert err is None

    def test_run_dedup_identical_tool_calls_in_batch(self):
        """批次内去重：同一 (工具名, 参数) 重复出现时仅执行一次，不重复触发。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        order_service = _fake_order_service()
        executor = ToolExecutor(
            order_service=order_service,
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        # 同一 query_order 出现两次（含别名 + 参数顺序不同，应判为重复）
        tool_calls = [
            {"id": "call_a", "type": "function",
             "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'}},
            {"id": "call_b", "type": "function",
             "function": {"name": "order_query", "arguments": '{"order_id": "A1001"}'}},
        ]
        state = _state()
        messages = asyncio.run(executor.run(tool_calls, state))

        # 仅一条消息 / 一条结果
        assert len(messages) == 1
        assert len(state.tool_results) == 1
        order_service.get_order_status.assert_called_once()
        # 保留首个（call_a）
        assert messages[0]["tool_call_id"] == "call_a"
        assert messages[0]["name"] == "query_order"

    def test_run_dedup_keeps_distinct_tools_and_args(self):
        """去重不应误伤：不同工具 / 同工具不同参数都保留。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []

        # 不同 order_id 返回不同数据，确保结果内容确实不同（否则跨轮去重会正确合并为一条）。
        order_service = MagicMock()

        def _get(oid: str):
            if oid == "A1001":
                return OrderInfo(order_id="A1001", status="已发货", product_name="键盘", amount=199.0)
            if oid == "B9999":
                return OrderInfo(order_id="B9999", status="待付款", product_name="鼠标", amount=99.0)
            return None

        order_service.get_order_status.side_effect = _get

        executor = ToolExecutor(
            order_service=order_service,
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {"id": "call_o", "type": "function",
             "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'}},
            {"id": "call_l", "type": "function",
             "function": {"name": "query_logistics", "arguments": '{"order_id": "A1001"}'}},
            {"id": "call_o2", "type": "function",
             "function": {"name": "query_order", "arguments": '{"order_id": "B9999"}'}},
        ]
        state = _state()
        messages = asyncio.run(executor.run(tool_calls, state))

        assert len(messages) == 3
        assert len(state.tool_results) == 3
        tools = {r.tool for r in state.tool_results}
        assert tools == {"query_order", "query_logistics"}
        # 同工具不同参数都保留：两个 order_id 都被真正查询
        called_ids = {c.args[0] for c in order_service.get_order_status.call_args_list}
        assert called_ids == {"A1001", "B9999"}

    def test_run_dedup_blocks_side_effect_replay_in_batch(self):
        """去重对副作用工具同样生效：同批次内重复 create_handoff 只建单一次。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        handoff_service = _fake_handoff_service()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=handoff_service,
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        tool_calls = [
            {"id": "call_h1", "type": "function",
             "function": {"name": "create_handoff", "arguments": "{}"}},
            {"id": "call_h2", "type": "function",
             "function": {"name": "create_handoff", "arguments": "{}"}},
        ]
        state = _state(summary="需要人工处理")
        asyncio.run(executor.run(tool_calls, state))

        handoff_service.create_handoff.assert_called_once()

    def test_dedup_tool_calls_helper(self):
        """_dedup_tool_calls 纯函数：返回去重列表 + 丢弃计数，参数顺序不同视为同一调用。"""
        tool_calls = [
            {"id": "a", "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'}},
            {"id": "b", "function": {"name": "query_order", "arguments": '{"order_id":"A1001"}'}},
            {"id": "c", "function": {"name": "query_logistics", "arguments": '{"order_id": "A1001"}'}},
        ]
        deduped, dropped = ToolExecutor._dedup_tool_calls(tool_calls)
        assert dropped == 1
        assert [tc["id"] for tc in deduped] == ["a", "c"]

    def test_run_cross_round_dedup_accumulated_results(self):
        """跨轮去重：多轮 ReAct 中 LLM 重复调用同一工具（同订单 → 相同结果）时，
        state.tool_results 不重复累加，最终回复不会出现两条相同物流信息。"""
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
            "id": "call_l",
            "type": "function",
            "function": {"name": "query_logistics", "arguments": '{"order_id": "A1001"}'},
        }
        state = _state()
        # 第 1 轮
        asyncio.run(executor.run([call], state))
        assert len(state.tool_results) == 1
        # 第 2 轮 LLM 又调了一次（相同订单 → 相同结果）
        asyncio.run(executor.run([call], state))
        # 仍只有 1 条，未重复累加
        assert len(state.tool_results) == 1
        assert state.tool_results[0].tool == "query_logistics"

    def test_run_cross_round_cache_skips_re_execution(self):
        """执行层缓存：跨轮重复调用同一工具时，handler 不再被真正执行（缓存命中）。

        这是从「结果层去重」前移到「执行层缓存」的关键收益——既不出重复回复，
        也不浪费一次工具执行（省延迟、避免副作用工具重复触发）。
        """
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        logistics_service = _fake_logistics_service()
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=logistics_service,
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        call = {
            "id": "call_l", "type": "function",
            "function": {"name": "query_logistics", "arguments": '{"order_id": "A1001"}'},
        }
        state = _state()
        # 第 1 轮执行
        asyncio.run(executor.run([call], state))
        # 第 2 轮重复调用（同订单）
        asyncio.run(executor.run([call], state))
        # handler 只被真正执行一次：第 2 轮命执行层缓存、跳过执行
        assert logistics_service.get_logistics.call_count == 1
        # 缓存已记录该调用
        assert state.tool_cache
        # 结果仍只有 1 条，未重复累加
        assert len(state.tool_results) == 1

    def test_run_cache_key_differs_by_args(self):
        """缓存按 (工具, 参数) 区分：不同参数视为不同调用，仍各自执行。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []

        order_service = MagicMock()

        def _get(oid: str):
            if oid == "A1001":
                return OrderInfo(order_id="A1001", status="已发货", product_name="键盘", amount=199.0)
            if oid == "B9999":
                return OrderInfo(order_id="B9999", status="待付款", product_name="鼠标", amount=99.0)
            return None

        order_service.get_order_status.side_effect = _get

        executor = ToolExecutor(
            order_service=order_service,
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        call_a = {
            "id": "c_a", "type": "function",
            "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'},
        }
        call_b = {
            "id": "c_b", "type": "function",
            "function": {"name": "query_order", "arguments": '{"order_id": "B9999"}'},
        }
        state = _state()
        asyncio.run(executor.run([call_a], state))
        # 不同参数：缓存未命中，正常执行
        asyncio.run(executor.run([call_b], state))
        assert order_service.get_order_status.call_count == 2
        assert len(state.tool_results) == 2

    def test_run_cross_round_distinct_results_kept(self):
        """跨轮去重不应误伤：不同订单（结果不同）跨轮调用仍各自保留。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []

        order_service = MagicMock()

        def _get(oid: str):
            if oid == "A1001":
                return OrderInfo(order_id="A1001", status="已发货", product_name="键盘", amount=199.0)
            if oid == "B9999":
                return OrderInfo(order_id="B9999", status="待付款", product_name="鼠标", amount=99.0)
            return None

        order_service.get_order_status.side_effect = _get

        executor = ToolExecutor(
            order_service=order_service,
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        call_a = {
            "id": "c_a",
            "type": "function",
            "function": {"name": "query_order", "arguments": '{"order_id": "A1001"}'},
        }
        call_b = {
            "id": "c_b",
            "type": "function",
            "function": {"name": "query_order", "arguments": '{"order_id": "B9999"}'},
        }
        state = _state()
        asyncio.run(executor.run([call_a], state))
        asyncio.run(executor.run([call_b], state))
        assert len(state.tool_results) == 2
        order_ids = {r.sanitized_result["order_id"] for r in state.tool_results}
        assert order_ids == {"A1001", "B9999"}

    def test_run_validation_error_blocks_handler_and_not_retried(self):
        """R5：参数非法时 run() 直接返回 error，handler 根本不被执行（自然也不重试）。"""
        rag_tool = MagicMock()
        rag_tool.run.return_value = []
        boom = MagicMock(side_effect=RuntimeError("不应被调用"))
        executor = ToolExecutor(
            order_service=_fake_order_service(),
            logistics_service=_fake_logistics_service(),
            handoff_service=_fake_handoff_service(),
            refund_service=RefundService(),
            rag_tool=rag_tool,
        )
        executor._handlers["request_refund"] = boom  # 即便换成会炸的 handler，也不应被调用
        # refund_type 非法枚举 → 校验失败
        tool_calls = [
            {
                "id": "call_v",
                "type": "function",
                "function": {"name": "request_refund", "arguments": '{"order_id": "A1001", "refund_type": "foo"}'},
            }
        ]
        state = _state()
        messages = asyncio.run(executor.run(tool_calls, state))
        # handler 未执行（校验在 handler 前拦截）
        assert boom.call_count == 0
        # 返回干净 error，而非「执行出错」那种基础设施兜底
        assert json.loads(messages[0]["content"])["kind"] == "error"
        assert "refund_type" in state.tool_results[-1].raw_result["message"]
