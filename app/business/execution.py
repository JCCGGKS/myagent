from __future__ import annotations

from app.schema import ConversationState, ToolExecutionResult
from app.business.domain import HandoffService, LogisticsService, OrderService
from app.utils import build_action_record


class ExecutionService:
    def __init__(
        self,
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
    ) -> None:
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service

    def run_tool(self, name: str, args: dict, state: ConversationState) -> ToolExecutionResult:
        """按工具名（LLM 函数调用或业务工具）执行，返回结构化结果。

        统一入口：rag_retrieve 由 agent_node 侧的 ToolExecutor 处理；
        此处负责订单/物流/转人工等业务工具。
        """
        if name in ("query_order", "order_query"):
            order_id = args.get("order_id") or state.slots.get("order_id")
            return self._query_order(order_id)
        if name in ("query_logistics", "logistics"):
            order_id = args.get("order_id") or state.slots.get("order_id")
            return self._query_logistics(order_id)
        if name in ("create_handoff", "handoff_service", "request_human"):
            # create_handoff 会写 state.tool_result / state.handoff 并返回 state
            self.create_handoff(state)
            return state.tool_result  # type: ignore[return-value]
        return ToolExecutionResult(kind="error", user_facing_summary=f"未知工具: {name}")

    def _query_order(self, order_id: str | None) -> ToolExecutionResult:
        if not order_id:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary="请提供订单号，以便我为您查询。",
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

    def execute_business_tool(self, state: ConversationState) -> ConversationState:
        """按意图/槽位驱动的业务工具入口（保留，供非 LLM 函数调用路径使用）。"""
        name = (
            "query_order"
            if state.current_sub_intent.startswith("order_query")
            else "query_logistics"
        )
        result = self.run_tool(name, {}, state)
        state.tool_result = result
        state.latest_action_name = "business_tool_executor"
        state.latest_action_result = result.sanitized_result
        state.action_history.append(build_action_record(name, result.user_facing_summary))
        return state

    def create_handoff(self, state: ConversationState) -> ConversationState:
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
        state.action_history.append(build_action_record("handoff_node", state.tool_result.user_facing_summary))
        return state
