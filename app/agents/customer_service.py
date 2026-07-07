from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import ActionRecord, ChatRequest, ChatResponse, ConversationState, ToolExecutionResult
from app.services import (
    HandoffClarificationPolicy,
    HandoffService,
    IntentRouterService,
    KnowledgeBaseService,
    LLMIntentFallbackService,
    LogisticsService,
    OrderService,
    StateTrackerService,
)
from app.store import SessionStore
from app.utils import normalize_whitespace

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "END"
    START = "START"
    StateGraph = None


MAX_RECENT_MESSAGES = 6
SOFT_SUMMARY_TURNS = 8


class CustomerServiceAgent:
    def __init__(
        self,
        store: SessionStore,
        knowledge_base: KnowledgeBaseService,
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
        llm_fallback_service: LLMIntentFallbackService | None = None,
    ) -> None:
        self.store = store
        self.knowledge_base = knowledge_base
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.intent_router_service = IntentRouterService(knowledge_base, llm_fallback_service)
        self.state_tracker_service = StateTrackerService()
        self.policy_service = HandoffClarificationPolicy()
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        if StateGraph is None:
            return None

        builder = StateGraph(dict)
        builder.add_node("input_normalizer", self.input_normalizer)
        builder.add_node("intent_router", self.intent_router)
        builder.add_node("state_tracker", self.state_tracker)
        builder.add_node("policy_layer", self.policy_layer)
        builder.add_node("clarification_node", self.clarification_node)
        builder.add_node("knowledge_retriever", self.knowledge_retriever)
        builder.add_node("business_tool_executor", self.business_tool_executor)
        builder.add_node("handoff_node", self.handoff_node)
        builder.add_node("response_generator", self.response_generator)
        builder.add_node("context_compressor", self.context_compressor)
        builder.add_node("memory_writer", self.memory_writer)

        builder.add_edge(START, "input_normalizer")
        builder.add_edge("input_normalizer", "intent_router")
        builder.add_edge("intent_router", "state_tracker")
        builder.add_edge("state_tracker", "policy_layer")
        builder.add_conditional_edges(
            "policy_layer",
            self.route_after_policy,
            {
                "clarification_node": "clarification_node",
                "knowledge_retriever": "knowledge_retriever",
                "business_tool_executor": "business_tool_executor",
                "handoff_node": "handoff_node",
                "response_generator": "response_generator",
            },
        )
        builder.add_edge("clarification_node", "context_compressor")
        builder.add_edge("knowledge_retriever", "response_generator")
        builder.add_edge("business_tool_executor", "response_generator")
        builder.add_edge("handoff_node", "response_generator")
        builder.add_edge("response_generator", "context_compressor")
        builder.add_edge("context_compressor", "memory_writer")
        builder.add_edge("memory_writer", END)
        return builder.compile()

    def chat(self, request: ChatRequest) -> ChatResponse:
        state = self._execute_request(request)
        return self._build_chat_response(state)

    def chat_events(self, request: ChatRequest) -> list[dict[str, Any]]:
        payload = self._build_payload(request)
        events: list[dict[str, Any]] = []

        payload = self.input_normalizer(payload)
        events.append({"type": "status", "stage": "input_normalizer", "message": "已接收用户消息"})

        payload = self.intent_router(payload)
        state = payload["state"]
        intent = state.intent_result
        events.append(
            {
                "type": "intent",
                "main_intent": intent.main_intent if intent else "unsupported",
                "sub_intent": intent.sub_intent if intent else "unsupported.unknown",
                "confidence": intent.confidence if intent else 0.0,
                "slots": intent.slots if intent else {},
                "needs_clarification": intent.needs_clarification if intent else False,
            }
        )

        payload = self.state_tracker(payload)
        state = payload["state"]
        events.append(
            {
                "type": "state",
                "stage": state.stage,
                "current_main_intent": state.current_main_intent,
                "current_sub_intent": state.current_sub_intent,
                "slots": state.slots,
                "missing_slots": state.missing_slots,
                "needs_clarification": state.needs_clarification,
            }
        )

        payload = self.policy_layer(payload)
        state = payload["state"]
        events.append({"type": "trace", "message": f"策略动作: {state.current_action}"})

        route = self.route_after_policy(payload)
        if route == "clarification_node":
            payload = self.clarification_node(payload)
            events.append({"type": "trace", "message": "进入澄清节点"})
        elif route == "knowledge_retriever":
            payload = self.knowledge_retriever(payload)
            events.append({"type": "trace", "message": "执行知识检索"})
        elif route == "business_tool_executor":
            payload = self.business_tool_executor(payload)
            state = payload["state"]
            events.append({"type": "tool_result", "tool_result": self._serialize_tool_result(state)})
        elif route == "handoff_node":
            payload = self.handoff_node(payload)
            state = payload["state"]
            events.append({"type": "tool_result", "tool_result": self._serialize_tool_result(state)})

        if route != "clarification_node":
            payload = self.response_generator(payload)

        payload = self.context_compressor(payload)
        payload = self.memory_writer(payload)
        state = payload["state"]
        events.append({"type": "final", "response": self._build_chat_response(state).model_dump()})
        return events

    def _execute_request(self, request: ChatRequest) -> ConversationState:
        payload = self._build_payload(request)
        if self.graph is None:
            payload = self._run_without_langgraph(payload)
        else:
            payload = self.graph.invoke(payload)
        return payload["state"]

    def _build_payload(self, request: ChatRequest) -> dict[str, Any]:
        state = self.store.get(request.session_id) or ConversationState(
            session_id=request.session_id,
            user_id=request.user_id,
            channel=request.channel,
        )
        return {"state": state, "request": request}

    def _run_without_langgraph(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self.input_normalizer(payload)
        payload = self.intent_router(payload)
        payload = self.state_tracker(payload)
        payload = self.policy_layer(payload)
        route = self.route_after_policy(payload)
        if route == "clarification_node":
            payload = self.clarification_node(payload)
        elif route == "knowledge_retriever":
            payload = self.knowledge_retriever(payload)
            payload = self.response_generator(payload)
        elif route == "business_tool_executor":
            payload = self.business_tool_executor(payload)
            payload = self.response_generator(payload)
        elif route == "handoff_node":
            payload = self.handoff_node(payload)
            payload = self.response_generator(payload)
        else:
            payload = self.response_generator(payload)
        payload = self.context_compressor(payload)
        payload = self.memory_writer(payload)
        return payload

    def input_normalizer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]
        message = normalize_whitespace(request.message)

        state.reply = ""
        state.intent_result = None
        state.retrieved_knowledge = []
        state.tool_result = None
        state.handoff = False
        state.handoff_reason = ""
        state.current_action = ""
        state.latest_action_result = None

        state.last_user_message = message
        state.channel = request.channel
        state.user_id = request.user_id
        state.message_history.append({"role": "user", "content": message})
        state.recent_messages.append({"role": "user", "content": message})
        payload["state"] = state
        return payload

    def intent_router(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        state.intent_result = self.intent_router_service.route(state, state.last_user_message)
        payload["state"] = state
        return payload

    def state_tracker(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        intent = state.intent_result
        if intent is None:
            return payload
        payload["state"] = self.state_tracker_service.apply(state, intent)
        return payload

    def policy_layer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        payload["state"] = self.policy_service.decide(state)
        return payload

    def route_after_policy(self, payload: dict[str, Any]) -> str:
        state: ConversationState = payload["state"]
        action = state.current_action
        if action in {"ask_intent_clarification", "ask_slot_clarification"}:
            return "clarification_node"
        if action == "retrieve_knowledge":
            return "knowledge_retriever"
        if action == "query_business_tool":
            return "business_tool_executor"
        if action == "handoff_human":
            return "handoff_node"
        return "response_generator"

    def clarification_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        if state.current_action == "ask_intent_clarification":
            state.reply = "我还不能准确判断你的诉求。你是想查订单、查物流、咨询退款，还是转人工？"
        elif "order_id" in state.missing_slots:
            if state.current_main_intent == "logistics_service":
                state.reply = "请提供订单号，我来帮你查询物流进度。"
            elif state.current_main_intent == "order_service":
                state.reply = "请提供订单号，我来帮你查询订单状态。"
            elif state.current_main_intent == "refund_service":
                state.reply = "请先提供订单号，我再帮你看退款规则或继续处理退款。"
            else:
                state.reply = "我还需要更多信息，麻烦补充一下你的问题。"
        else:
            state.reply = "我需要更多信息才能继续处理，或者可以直接帮你转人工。"
        state.latest_action_name = "clarification_node"
        state.latest_action_result = {"reply": state.reply}
        state.action_history.append(self._action_record("clarification_node", state.reply))
        payload["state"] = state
        return payload

    def knowledge_retriever(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        hits = self.knowledge_base.search(state.last_user_message)
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
        state.action_history.append(self._action_record("knowledge_retriever", summary))
        payload["state"] = state
        return payload

    def business_tool_executor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
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
        state.action_history.append(self._action_record(tool_name, state.tool_result.user_facing_summary))
        payload["state"] = state
        return payload

    def handoff_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
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
        state.action_history.append(self._action_record("handoff_node", state.tool_result.user_facing_summary))
        payload["state"] = state
        return payload

    def response_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        if state.reply:
            return payload

        if state.current_main_intent == "faq":
            state.reply = (
                state.tool_result.user_facing_summary
                if state.tool_result and state.tool_result.user_facing_summary
                else "我暂时没有检索到明确规则，你可以换一种说法，或者我帮你转人工。"
            )
        elif state.current_sub_intent == "refund_service.consult_policy":
            state.reply = (
                state.tool_result.user_facing_summary
                if state.tool_result and state.tool_result.user_facing_summary
                else "退款规则我暂时没有准确命中，你可以补充订单号或具体问题。"
            )
        elif state.current_sub_intent == "refund_service.request_refund":
            state.reply = "已收到你的退款诉求。请提供订单号后，我可以继续帮你确认下一步处理方式。"
        elif state.current_sub_intent == "order_service.query_status":
            tool_data = state.tool_result.sanitized_result if state.tool_result else None
            if tool_data:
                state.reply = (
                    f"订单 {tool_data['order_id']} 当前状态为 {tool_data['status']}，"
                    f"商品是 {tool_data['product_name']}，金额 {tool_data['amount']} 元。"
                )
            else:
                state.reply = "没有查到这个订单号，请确认后重试，或者我可以帮你转人工。"
        elif state.current_sub_intent == "logistics_service.query_status":
            tool_data = state.tool_result.sanitized_result if state.tool_result else None
            if tool_data and tool_data.get("timeline"):
                latest = tool_data["timeline"][-1]
                state.reply = (
                    f"订单 {tool_data['order_id']} 当前物流状态为 {tool_data['tracking_status']}，"
                    f"最近一条记录是 {latest['time']} {latest['status']}。"
                )
            else:
                state.reply = "没有查到该订单的物流信息，请确认订单号是否正确。"
        elif state.current_main_intent == "handoff_service":
            handoff_data = state.tool_result.sanitized_result if state.tool_result else {}
            state.reply = (
                f"已为你转人工客服，服务单号 {handoff_data.get('ticket_id', 'N/A')}。"
                "人工客服会基于当前会话上下文继续处理。"
            )
        elif state.current_sub_intent == "chitchat.greeting":
            state.reply = "你好，我可以帮你查询 FAQ、订单、物流、退款规则，也可以为你转人工客服。"
        elif state.current_sub_intent == "chitchat.thanks":
            state.reply = "不客气。如果你还想查询订单、物流或退款问题，我可以继续帮你处理。"
        else:
            state.reply = "这个问题我暂时无法准确处理。你可以换一种说法，或者我可以帮你转人工。"

        state.latest_action_name = state.latest_action_name or "response_generator"
        state.latest_action_result = {"reply": state.reply}
        if not state.action_history or state.action_history[-1].action_name != "response_generator":
            state.action_history.append(self._action_record("response_generator", state.reply))
        payload["state"] = state
        return payload

    def context_compressor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        state.message_history.append({"role": "assistant", "content": state.reply})
        state.recent_messages.append({"role": "assistant", "content": state.reply})

        if len(state.recent_messages) > MAX_RECENT_MESSAGES:
            overflow = state.recent_messages[:-MAX_RECENT_MESSAGES]
            state.recent_messages = state.recent_messages[-MAX_RECENT_MESSAGES:]
            overflow_summary = " ".join(
                f"{item['role']}:{item['content']}" for item in overflow if item.get("content")
            )
            if overflow_summary:
                state.running_summary = " ".join(
                    item for item in [state.running_summary, overflow_summary] if item
                ).strip()

        if len(state.message_history) >= SOFT_SUMMARY_TURNS * 2 and not state.running_summary:
            state.running_summary = self.state_tracker_service.build_state_summary(state)

        state.summary = self.state_tracker_service.build_state_summary(state)
        payload["state"] = state
        return payload

    def memory_writer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]

        self.store.append_message(state.session_id, "user", request.message)
        self.store.append_message(
            state.session_id,
            "assistant",
            state.reply,
            message_type="clarification" if state.current_action.startswith("ask_") else "text",
        )

        if state.tool_result:
            self.store.record_tool_call(
                session_id=state.session_id,
                tool_name=state.latest_action_name or state.tool_result.kind,
                tool_category=self._tool_category(state),
                request_args=dict(state.slots),
                raw_result=state.tool_result.raw_result,
                sanitized_result=state.tool_result.sanitized_result,
                user_facing_summary=state.tool_result.user_facing_summary,
            )

        if state.handoff:
            self.store.record_handoff(
                session_id=state.session_id,
                handoff_reason=state.handoff_reason or "policy_decision",
                handoff_summary=state.summary,
                state_snapshot=self._build_session_snapshot(state),
            )

        self.store.save(state)
        payload["state"] = state
        return payload

    def _build_chat_response(self, state: ConversationState) -> ChatResponse:
        return ChatResponse(
            reply=state.reply,
            main_intent=state.current_main_intent,
            sub_intent=state.current_sub_intent,
            stage=state.stage,
            needs_clarification=state.needs_clarification,
            handoff=state.handoff,
            slots=state.slots,
            missing_slots=state.missing_slots,
            summary=state.summary,
            emotion=state.emotion,
            current_action=state.current_action,
            running_summary=state.running_summary,
            tool_result=state.tool_result,
            session_state=self._build_session_snapshot(state),
            turn_trace=self._build_turn_trace(state),
        )

    def _build_session_snapshot(self, state: ConversationState) -> dict[str, Any]:
        return {
            "session_id": state.session_id,
            "user_id": state.user_id,
            "channel": state.channel,
            "current_main_intent": state.current_main_intent,
            "current_sub_intent": state.current_sub_intent,
            "stage": state.stage,
            "slots": state.slots,
            "missing_slots": state.missing_slots,
            "confirmed_slots": state.confirmed_slots,
            "candidate_intents": state.candidate_intents,
            "needs_clarification": state.needs_clarification,
            "handoff": state.handoff,
            "handoff_reason": state.handoff_reason,
            "summary": state.summary,
            "running_summary": state.running_summary,
            "risk_level": state.risk_level,
            "emotion": state.emotion.model_dump(),
            "current_action": state.current_action,
            "latest_action_name": state.latest_action_name,
            "latest_action_result": state.latest_action_result,
            "action_history": [item.model_dump() for item in state.action_history],
            "recent_messages": state.recent_messages,
            "message_history": state.message_history,
            "reply": state.reply,
            "archived_states": state.archived_states,
        }

    def _build_turn_trace(self, state: ConversationState) -> list[str]:
        trace = [
            f"识别主意图: {state.current_main_intent}",
            f"识别子意图: {state.current_sub_intent}",
            f"当前阶段: {state.stage}",
            f"策略动作: {state.current_action}",
            f"情绪: {state.emotion.primary}/{state.emotion.trend}",
        ]
        if state.slots:
            trace.append(f"已填槽位: {state.slots}")
        if state.missing_slots:
            trace.append(f"缺失槽位: {state.missing_slots}")
        if state.tool_result:
            trace.append(f"工具调用结果: {state.tool_result.kind}")
        if state.handoff:
            trace.append(f"触发转人工: {state.handoff_reason or 'policy_decision'}")
        if state.running_summary:
            trace.append(f"运行摘要: {state.running_summary}")
        return trace

    def _action_record(self, action_name: str, summary: str) -> ActionRecord:
        return ActionRecord(
            action_name=action_name,
            summary=summary,
            created_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        )

    def _serialize_tool_result(self, state: ConversationState) -> dict[str, Any] | None:
        return state.tool_result.model_dump() if state.tool_result else None

    def _tool_category(self, state: ConversationState) -> str:
        if state.current_action == "retrieve_knowledge":
            return "retrieval"
        if state.current_action == "handoff_human":
            return "workflow"
        return "query"
