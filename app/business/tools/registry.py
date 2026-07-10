"""工具 schema 注册中心。

把所有可供 LLM 函数调用（function calling）的工具 schema 汇总到
``build_tool_schemas()``，由 ``agent_node`` 注册到 LLM 的 tools 参数。

新增工具只需在下方补一个 ``_xxx_tool_schema()`` 并加入 ``build_tool_schemas()``
的返回列表；工具的执行逻辑仍由 ``tool_executor.ToolExecutor`` 按 name 分发，
二者通过工具名对齐（见 ``tool_executor._execute_one`` 的别名匹配）。
"""

from __future__ import annotations

from typing import Any

from app.business.tools.rag_tool import RagRetrieveTool


def _order_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": (
                "查询指定订单的状态、商品、金额等信息。"
                "当用户提供订单号并询问订单状态、发货情况、订单详情时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"}
                },
                "required": ["order_id"],
            },
        },
    }


def _logistics_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "query_logistics",
            "description": (
                "查询指定订单的物流配送进度与最新节点。"
                "当用户询问快递到哪了、物流更新、配送进度、是否签收时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"}
                },
                "required": ["order_id"],
            },
        },
    }


def _handoff_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "create_handoff",
            "description": (
                "转接人工客服：创建人工服务单，并基于当前会话上下文继续处理。"
                "当用户明确要求人工客服、情绪激动/投诉升级，或多次澄清仍无法解决时调用。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def build_tool_schemas() -> list[dict[str, Any]]:
    """汇总所有可调用工具的 OpenAI tools schema。

    LLM 注册后，ReAct 循环即可按需调用 RAG 检索、订单查询、物流查询与转人工。
    """
    return [
        RagRetrieveTool().to_tool_schema(),
        _order_tool_schema(),
        _logistics_tool_schema(),
        _handoff_tool_schema(),
    ]
