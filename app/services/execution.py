from __future__ import annotations

from app.models import ConversationState, ToolExecutionResult
from app.services.domain import HandoffService, KnowledgeBaseService, LogisticsService, OrderService
from app.utils import build_action_record


class ExecutionService:
    def __init__(
        self,
        knowledge_base: KnowledgeBaseService | None,
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service

    def retrieve_knowledge(self, state: ConversationState) -> ConversationState:
        hits = self.knowledge_base.search(state.last_user_message) if self.knowledge_base else []
        state.retrieved_knowledge = hits
        summary = hits[0].answer if hits else "未命中知识库答案"
        state.tool_result = ToolExecutionResult(
            kind="knowledge",
            raw_result={"hits": [hit.model_dump() for hit in hits]},
            sanitized_result=hits[0].model_dump() if hits else None,
            user_facing_summary=summary,
        )
        state.latest_action_name = "knowledge_retriever"
        state.latest_action_result = state.tool_result.sanitized_result
        state.action_history.append(build_action_record("knowledge_retriever", summary))
        return state

    def execute_business_tool(self, state: ConversationState) -> ConversationState:
        order_id = state.slots["order_id"]

        if state.current_sub_intent == "order_service.query_status":
            order = self.order_service.get_order_status(order_id)
            raw = order.model_dump() if order else None
            summary = f"订单 {order_id} 当前状态为 {order.status}" if order else "没有查到这个订单号"
            state.tool_result = ToolExecutionResult(
                kind="order",
                raw_result=raw,
                sanitized_result=raw,
                user_facing_summary=summary,
            )
            tool_name = "query_order"
        else:
            logistics = self.logistics_service.get_logistics(order_id)
            raw = logistics.model_dump() if logistics else None
            latest_status = logistics.timeline[-1].status if logistics and logistics.timeline else "无"
            summary = (
                f"订单 {order_id} 当前物流状态为 {logistics.tracking_status}，最近节点 {latest_status}"
                if logistics
                else "没有查到物流信息"
            )
            state.tool_result = ToolExecutionResult(
                kind="logistics",
                raw_result=raw,
                sanitized_result=raw,
                user_facing_summary=summary,
            )
            tool_name = "query_logistics"

        state.latest_action_name = "business_tool_executor"
        state.latest_action_result = state.tool_result.sanitized_result
        state.action_history.append(build_action_record(tool_name, state.tool_result.user_facing_summary))
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
