"""测试 AgentNodeService 的「已执行工具注入上下文」与「终态硬中断」。

- 每轮把本 turn 已执行过的工具清单注入系统提示，从源头降低重复调用概率；
- 工具结果含 handoff / confirmation 终态时，直接结束 ReAct 循环，不再调下一轮
  LLM（信号源为代码产出的 ToolExecutionResult.kind，确定可靠，不依赖 LLM 自觉停止）；
  success / error 等非终态不中断，避免砍掉合法后续调用。
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

from app.business.agent.agent_node import AgentNodeService
from app.business.prompts import build_agent_system_prompt
from app.business.tools.domain import (
    HandoffService,
    LogisticsService,
    OrderService,
    RefundService,
)
from app.business.tools.tool_executor import ToolExecutor
from app.schema import ConversationState, ToolExecutionResult


def _state() -> ConversationState:
    return ConversationState(
        session_id="es-session",
        user_id=1,
        channel="web",
        recent_messages=[{"role": "user", "content": "查一下 A1001 的物流"}],
    )


def _executor() -> ToolExecutor:
    return ToolExecutor(
        order_service=OrderService(),
        logistics_service=LogisticsService(),
        handoff_service=HandoffService(),
        refund_service=RefundService(),
    )


def _tc(name: str, args: dict) -> dict:
    return {
        "id": "c",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _svc() -> AgentNodeService:
    return AgentNodeService(tool_executor=_executor(), max_tool_rounds=3)


def test_prompt_includes_executed_tools():
    """build_agent_system_prompt 应把本 turn 已执行工具渲染进提示词（参数可读）。"""
    state = _state()
    # 模拟执行层缓存已记录两次调用（key 形如 canonical:{json args}）
    state.tool_cache = {
        'query_logistics:{"order_id": "A1001"}': 0,
        'query_order:{"order_id": "B9999"}': 1,
    }
    prompt = build_agent_system_prompt(state)
    assert "本 turn 你已经调用过以下工具" in prompt
    assert "query_logistics(order_id=A1001)" in prompt
    assert "query_order(order_id=B9999)" in prompt


def test_prompt_empty_when_no_executed_tools():
    """本 turn 尚无任何工具执行时，提示词不应出现「已调用」清单。"""
    state = _state()
    state.tool_cache = {}
    prompt = build_agent_system_prompt(state)
    assert "本 turn 你已经调用过以下工具" not in prompt


@patch("app.business.agent.agent_node.call_llm_async")
def test_executed_tools_injected_each_round(mock_llm):
    """每轮刷新系统提示：round2 的 LLM 调用应能看到 round1 已执行的工具清单。"""
    call = _tc("query_logistics", {"order_id": "A1001"})
    mock_llm.side_effect = [
        {"tool_calls": [call]},                       # round 1：执行
        {"content": "已查到。", "tool_calls": None},   # round 2：收尾
    ]
    state = _state()
    asyncio.run(_svc().run(state))

    # round2（第 2 次 LLM 调用）的 messages[0] 系统提示须含已执行工具
    second_messages = mock_llm.call_args_list[1].args[2]
    sys_prompt = second_messages[0]["content"]
    assert "query_logistics(order_id=A1001)" in sys_prompt


def _svc_with_tool_result(result: ToolExecutionResult, call: dict) -> "AgentNodeService":
    """构造一个 AgentNodeService：其 tool_executor.run 直接注入给定 kind 的工具结果，
    隔离 domain 数据，专测 agent 循环的「终态硬中断」判定。"""
    svc = _svc()

    async def fake_run(tool_calls, state):
        state.tool_results = state.tool_results or []
        state.tool_cache = state.tool_cache or {}
        # 模拟真实 executor：每次执行都向 tool_cache 写入新键（与 run 行为一致），
        # 否则「ReAct stopping guard」会因 cache 未增长而误判为全缓存命中、提前 break。
        for tc in tool_calls:
            state.tool_results.append(result)
            key = f"{tc['function']['name']}:{tc['function'].get('arguments', '{}')}"
            state.tool_cache[key] = len(state.tool_results) - 1
        return [
            {
                "role": "tool",
                "tool_call_id": call.get("id"),
                "name": call["function"]["name"],
                "content": "{}",
            }
        ]

    svc.tool_executor.run = fake_run
    return svc


@patch("app.business.agent.agent_node.call_llm_async")
def test_terminal_break_on_handoff(mock_llm):
    """工具结果含 handoff → 终态硬中断，不再调下一轮 LLM（省掉 LLM 误补 create_handoff）。"""
    call = _tc("request_refund", {"order_id": "A1001", "refund_type": "refund", "confirm": False})
    mock_llm.return_value = {"tool_calls": [call]}  # 若未中断会一直消费
    result = ToolExecutionResult(kind="handoff", raw_result={"handoff_ticket_id": "H1"})
    state = _state()
    asyncio.run(_svc_with_tool_result(result, call).run(state))
    # 关键：LLM 仅被调用 1 次（handoff 终态直接 break）。
    assert mock_llm.call_count == 1
    assert any(getattr(r, "kind", None) == "handoff" for r in state.tool_results)


@patch("app.business.agent.agent_node.call_llm_async")
def test_terminal_break_on_confirmation(mock_llm):
    """工具结果含 confirmation（R1 挂起）→ 终态硬中断，等待用户下一轮确认。"""
    call = _tc("request_refund", {"order_id": "A1001", "refund_type": "refund", "confirm": False})
    mock_llm.return_value = {"tool_calls": [call]}
    result = ToolExecutionResult(kind="confirmation", raw_result={"order_id": "A1001", "confirmed": False})
    state = _state()
    asyncio.run(_svc_with_tool_result(result, call).run(state))
    assert mock_llm.call_count == 1
    assert any(getattr(r, "kind", None) == "confirmation" for r in state.tool_results)


@patch("app.business.agent.agent_node.call_llm_async")
def test_no_break_on_success_kind(mock_llm):
    """success 不是终态 → 不硬中断，循环继续到 LLM 自然收尾（避免砍掉合法后续调用）。"""
    call = _tc("query_order", {"order_id": "A1001"})
    mock_llm.side_effect = [
        {"tool_calls": [call]},                       # round 1：success
        {"content": "已查到。", "tool_calls": None},   # round 2：LLM 自然收尾
    ]
    result = ToolExecutionResult(kind="success", raw_result={"order_id": "A1001"})
    state = _state()
    asyncio.run(_svc_with_tool_result(result, call).run(state))
    # success 不中断 → 跑到 round2 收尾，共 2 次 LLM 调用。
    assert mock_llm.call_count == 2

