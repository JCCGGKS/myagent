"""测试 AgentNodeService 的早停启发式与「已执行工具注入上下文」。

冗余调用场景：多轮 ReAct 中 LLM 重复发出已执行过的 tool_call（全部命中执行层缓存、
未产生任何新查询）→ 早停跳出循环，省掉冗余的下一轮 LLM 往返；而只要本轮出现一个新
查询（缓存未命中），循环照常继续。同时，每轮把本 turn 已执行过的工具清单注入系统提示，
从源头降低重复调用概率。
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
from app.schema import ConversationState


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


@patch("app.business.agent.agent_node.call_llm_async")
def test_early_stop_on_redundant_cache_hit(mock_llm):
    """第 1 轮查询（新执行），第 2 轮重复同一查询（全命中缓存）→ 早停，不再调第 3 轮 LLM。"""
    call = _tc("query_logistics", {"order_id": "A1001"})
    # 提供 3 个响应以防 side_effect 耗尽；若早停失效会消费到第 3 个（call_count==3）。
    mock_llm.side_effect = [
        {"tool_calls": [call]},  # round 1：新执行
        {"tool_calls": [call]},  # round 2：缓存命中 → 早停
        {"tool_calls": [call]},  # 不应被消费
    ]
    state = _state()
    asyncio.run(_svc().run(state))

    # 关键：LLM 只被调用 2 次（round1 + round2），第 3 轮被早停跳过。
    assert mock_llm.call_count == 2
    # 工具仅真正执行一次，结果唯一一条。
    assert len(state.tool_results) == 1
    assert state.tool_results[0].tool == "query_logistics"
    # 调过工具 → reply 留空交 response_generator（与既有设计一致）。
    assert state.reply == ""


@patch("app.business.agent.agent_node.call_llm_async")
def test_no_early_stop_when_new_call_present(mock_llm):
    """本轮出现新查询（缓存未命中）→ 不早停，循环继续；最终以无 tool_calls 正常收尾。"""
    logistics = _tc("query_logistics", {"order_id": "A1001"})  # round1 新；round2 命中
    order = _tc("query_order", {"order_id": "B9999"})           # round2 新 → 不早停
    mock_llm.side_effect = [
        {"tool_calls": [logistics]},                       # round 1：新执行
        {"tool_calls": [logistics, order]},                # round 2：一个命中 + 一个新 → 继续
        {"content": "已为您查到相关信息。", "tool_calls": None},  # round 3：无 tool_calls → 收尾
    ]
    state = _state()
    asyncio.run(_svc().run(state))

    # 因 round2 含新查询，未早停，循环跑满到 round3 收尾。
    assert mock_llm.call_count == 3
    # 两个不同查询都真正执行，结果各一条。
    assert len(state.tool_results) == 2
    tools = {r.tool for r in state.tool_results}
    assert tools == {"query_logistics", "query_order"}


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
