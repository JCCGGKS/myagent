from __future__ import annotations

from typing import Any

from app.models import ChatRequest, ChatResponse, ConversationState, ToolExecutionResult
from app.rag import KnowledgeBaseService
from app.services import (
    ClarificationService,
    ContextService,
    ExecutionService,
    HandoffClarificationPolicy,
    HandoffService,
    IntentRouterService,
    IntentSchemaRegistry,
    LLMIntentFallbackService,
    LogisticsService,
    MemoryService,
    OrderService,
    ResponseService,
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
        self.intent_schema_registry = IntentSchemaRegistry()
        self.intent_router_service = IntentRouterService(knowledge_base, llm_fallback_service)
        self.state_tracker_service = StateTrackerService(schema_registry=self.intent_schema_registry)
        self.policy_service = HandoffClarificationPolicy()
        self.clarification_service = ClarificationService()
        self.execution_service = ExecutionService(
            knowledge_base=knowledge_base,
            order_service=order_service,
            logistics_service=logistics_service,
            handoff_service=handoff_service,
        )
        self.context_service = ContextService(state_tracker=self.state_tracker_service)
        self.response_service = ResponseService()
        self.memory_service = MemoryService(store)
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
        payload["state"] = self.clarification_service.generate(state)
        return payload

    def knowledge_retriever(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        payload["state"] = self.execution_service.retrieve_knowledge(state)
        return payload

    def business_tool_executor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        payload["state"] = self.execution_service.execute_business_tool(state)
        return payload

    def handoff_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        payload["state"] = self.execution_service.create_handoff(state)
        return payload

    def response_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        payload["state"] = self.response_service.generate(state)
        return payload

    def context_compressor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        payload["state"] = self.context_service.compress(state)
        return payload

    def memory_writer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]
        payload["state"] = self.memory_service.persist(state, request)
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

    def _serialize_tool_result(self, state: ConversationState) -> dict[str, Any] | None:
        return state.tool_result.model_dump() if state.tool_result else None
