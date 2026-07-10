from __future__ import annotations

import json
import logging
from typing import Any

from app.schema import ConversationState, ToolExecutionResult
from app.business.tools.domain import HandoffService, LogisticsService, OrderService
from app.business.tools.rag_tool import RagRetrieveTool
from app.utils import build_action_record

logger = logging.getLogger(__name__)


class ToolExecutor:
    """统一的工具执行服务：覆盖 LLM 函数调用工具与业务工具。

    业务工具（订单/物流/转人工）由 domain 服务直接驱动；知识检索
    （``rag_retrieve``）由 ``rag_tool`` 驱动。``agent_node`` 调用 ``run``
    执行一批 tool_calls，返回 tool 结果消息（追加到 ReAct 线程），并把
    最后一次结果写入 ``state.tool_result``。
    """

    def __init__(
        self,
        order_service: OrderService | None = None,
        logistics_service: LogisticsService | None = None,
        handoff_service: HandoffService | None = None,
        rag_tool: RagRetrieveTool | None = None,
    ) -> None:
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.rag_tool = rag_tool or RagRetrieveTool()

    def run(
        self, tool_calls: list[dict[str, Any]], state: ConversationState
    ) -> list[dict[str, Any]]:
        tool_messages: list[dict[str, Any]] = []
        last_result: ToolExecutionResult | None = None
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            result = self._execute_one(name, args, state)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": name,
                    "content": json.dumps(
                        result.model_dump() if isinstance(result, ToolExecutionResult) else result,
                        ensure_ascii=False,
                    ),
                }
            )
            if isinstance(result, ToolExecutionResult):
                last_result = result
        if last_result is not None:
            state.tool_result = last_result
        return tool_messages

    def _execute_one(
        self, name: str, args: dict[str, Any], state: ConversationState
    ) -> ToolExecutionResult:
        logger.info("ToolExecutor: executing %s args=%s", name, args)
        if name == "rag_retrieve":
            return self._rag_retrieve(args, state)
        if name in ("query_order", "order_query"):
            order_id = args.get("order_id") or state.slots.get("order_id")
            return self._query_order(order_id)
        if name in ("query_logistics", "logistics"):
            order_id = args.get("order_id") or state.slots.get("order_id")
            return self._query_logistics(order_id)
        if name in ("create_handoff", "handoff_service", "request_human"):
            return self.create_handoff(state)
        return ToolExecutionResult(kind="error", user_facing_summary=f"未知工具: {name}")

    def _rag_retrieve(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        docs = self.rag_tool.run(args.get("query", ""), user_id=state.user_id)
        return ToolExecutionResult(
            kind="knowledge",
            raw_result={"retrieved_docs": docs},
            sanitized_result={"retrieved_docs": docs},
            user_facing_summary=f"检索到 {len(docs)} 条相关文档",
        )

    def _query_order(self, order_id: str | None) -> ToolExecutionResult:
        if not order_id:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary="请提供订单号，以便我为您查询。",
            )
        if self.order_service is None:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary=f"订单服务未配置，无法查询: {order_id}",
            )
        order = self.order_service.get_order_status(order_id)
        raw = order.model_dump() if order else None
        summary = f"订单 {order_id} 当前状态为 {order.status}" if order else "没有查到这个订单号"
        return ToolExecutionResult(
            kind="order_query",
            raw_result=raw,
            sanitized_result=raw,
            user_facing_summary=summary,
        )

    def _query_logistics(self, order_id: str | None) -> ToolExecutionResult:
        if not order_id:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary="请提供订单号，以便我为您查询物流。",
            )
        if self.logistics_service is None:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary=f"物流服务未配置，无法查询: {order_id}",
            )
        logistics = self.logistics_service.get_logistics(order_id)
        raw = logistics.model_dump() if logistics else None
        latest_status = (
            logistics.timeline[-1].status
            if logistics and logistics.timeline
            else "无"
        )
        summary = (
            f"订单 {order_id} 当前物流状态为 {logistics.tracking_status}，最近节点 {latest_status}"
            if logistics
            else "没有查到物流信息"
        )
        return ToolExecutionResult(
            kind="logistics",
            raw_result=raw,
            sanitized_result=raw,
            user_facing_summary=summary,
        )

    def create_handoff(self, state: ConversationState) -> ConversationState:
        if self.handoff_service is None:
            state.tool_result = ToolExecutionResult(
                kind="error",
                user_facing_summary="转人工服务未配置，无法创建服务单。",
            )
            return state
        handoff = self.handoff_service.create_handoff(state.session_id, state.summary)
        state.tool_result = ToolExecutionResult(
            kind="handoff",
            raw_result=handoff.model_dump(),
            sanitized_result=handoff.model_dump(),
            user_facing_summary=f"已创建人工服务单 {handoff.ticket_id}",
        )
        state.handoff = True
        state.latest_action_name = "handoff_node"
        state.latest_action_result = state.tool_result.sanitized_result
        state.action_history.append(
            build_action_record("handoff_node", state.tool_result.user_facing_summary)
        )
        return state
