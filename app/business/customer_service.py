from __future__ import annotations

import logging
from typing import Any

from app.schema import ChatRequest, ChatResponse, ConversationState, ToolExecutionResult

logger = logging.getLogger(__name__)
from app.business.agent_node import AgentNodeService
from app.business import (
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
from app.dao import SessionStore
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
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
        llm_fallback_service: LLMIntentFallbackService | None = None,
    ) -> None:
        self.store = store
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.intent_schema_registry = IntentSchemaRegistry()
        self.intent_router_service = IntentRouterService(llm_fallback_service=llm_fallback_service)
        self.state_tracker_service = StateTrackerService(schema_registry=self.intent_schema_registry)
        self.policy_service = HandoffClarificationPolicy()
        self.clarification_service = ClarificationService()
        self.execution_service = ExecutionService(
            order_service=order_service,
            logistics_service=logistics_service,
            handoff_service=handoff_service,
        )
        self.context_service = ContextService(state_tracker=self.state_tracker_service)
        self.response_service = ResponseService()
        self.memory_service = MemoryService(store)
        # agent_node 初始化（工具调用节点）
        self.agent_node_service = AgentNodeService(
            llm=None,  # TODO: 接入真实 LLM
            tools=None,  # 会从默认工具列表加载
        )
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
        # agent_node 替代 business_tool_executor 和 knowledge_retriever
        builder.add_node("agent_node", self.agent_node)
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
                "agent_node": "agent_node",
                "handoff_node": "handoff_node",
                "response_generator": "response_generator",
            },
        )
        builder.add_edge("clarification_node", "context_compressor")
        # agent_node 执行完后，路由到 response_generator
        builder.add_edge("agent_node", "response_generator")
        builder.add_edge("handoff_node", "response_generator")
        builder.add_edge("response_generator", "context_compressor")
        builder.add_edge("context_compressor", "memory_writer")
        builder.add_edge("memory_writer", END)
        return builder.compile()

    def chat(self, request: ChatRequest) -> ChatResponse:
        logger.info("chat start session=%s message=%r", request.session_id, request.message[:80])
        state = self._execute_request(request)
        logger.info(
            "chat done session=%s intent=%s.%s action=%s",
            request.session_id,
            state.current_main_intent, state.current_sub_intent, state.current_action,
        )
        return self._build_chat_response(state)

    def chat_events(self, request: ChatRequest) -> list[dict[str, Any]]:
        """LangGraph 图驱动的事件生成（与 chat() 行为一致）。"""
        if self.graph is None:
            return self._chat_events_fallback(request)
        payload = self._build_payload(request)
        events: list[dict[str, Any]] = []
        for chunk in self.graph.stream(payload):
            for node_name, node_payload in chunk.items():
                # node_payload is the full payload dict: {"state": ..., "request": ...}
                state = node_payload.get("state") if isinstance(node_payload, dict) else node_payload
                if state:
                    events.extend(self._node_state_to_events(node_name, state))
        return events

    def _chat_events_fallback(self, request: ChatRequest) -> list[dict[str, Any]]:
        """LangGraph 不可用时的降级路径（手动串联，逻辑与图一致）。"""
        payload = self._build_payload(request)
        events: list[dict[str, Any]] = []

        payload = self.input_normalizer(payload)
        events.extend(self._node_state_to_events("input_normalizer", payload["state"]))

        payload = self.intent_router(payload)
        events.extend(self._node_state_to_events("intent_router", payload["state"]))

        payload = self.state_tracker(payload)
        events.extend(self._node_state_to_events("state_tracker", payload["state"]))

        payload = self.policy_layer(payload)
        events.extend(self._node_state_to_events("policy_layer", payload["state"]))

        route = self.route_after_policy(payload)
        if route == "clarification_node":
            payload = self.clarification_node(payload)
            events.extend(self._node_state_to_events("clarification_node", payload["state"]))
        elif route == "knowledge_retriever":
            payload = self.knowledge_retriever(payload)
            events.extend(self._node_state_to_events("knowledge_retriever", payload["state"]))
            payload = self.response_generator(payload)
            events.extend(self._node_state_to_events("response_generator", payload["state"]))
        elif route == "business_tool_executor":
            payload = self.business_tool_executor(payload)
            events.extend(self._node_state_to_events("business_tool_executor", payload["state"]))
        elif route == "handoff_node":
            payload = self.handoff_node(payload)
            events.extend(self._node_state_to_events("handoff_node", payload["state"]))

        if route != "clarification_node":
            payload = self.response_generator(payload)
            events.extend(self._node_state_to_events("response_generator", payload["state"]))

        payload = self.context_compressor(payload)
        events.extend(self._node_state_to_events("context_compressor", payload["state"]))

        payload = self.memory_writer(payload)
        events.extend(self._node_state_to_events("memory_writer", payload["state"]))

        return events

    def _node_state_to_events(self, node_name: str, state: ConversationState) -> list[dict[str, Any]]:
        """将节点执行后的状态转为事件列表（供 chat_events 和 graph.stream 共用）。"""
        events: list[dict[str, Any]] = []
        if node_name == "intent_router":
            intent = state.intent_result
            events.append(
                {
                    "type": "intent",
                    "main_intent": intent.main_intent if intent else "unrecognize",
                    "sub_intent": intent.sub_intent if intent else "unrecognize.unknown",
                    "confidence": intent.confidence if intent else 0.0,
                    "slots": intent.slots if intent else {},
                    "needs_clarification": intent.needs_clarification if intent else False,
                }
            )
        elif node_name == "state_tracker":
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
        elif node_name in {"business_tool_executor", "handoff_node"}:
            if state.tool_result:
                events.append({"type": "tool_result", "tool_result": self._serialize_tool_result(state)})
        elif node_name == "response_generator":
            events.append({"type": "final", "response": self._build_chat_response(state).model_dump()})
        # 其他节点不推事件（或推通用 trace）
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
        logger.debug("node=input_normalizer session=%s message=%r", state.session_id, message[:80])

        state.reply = ""
        state.intent_result = None
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
        logger.debug("node=intent_router session=%s", state.session_id)
        state.intent_result = self.intent_router_service.route(state, state.last_user_message)
        logger.debug(
            "node=intent_router result intent=%s.%s source=%s",
            state.intent_result.main_intent if state.intent_result else None,
            state.intent_result.sub_intent if state.intent_result else None,
            state.intent_result.route_source if state.intent_result else None,
        )
        payload["state"] = state
        return payload

    def state_tracker(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        intent = state.intent_result
        if intent is None:
            logger.warning("state_tracker: no intent_result session=%s", state.session_id)
            return payload
        logger.debug("node=state_tracker session=%s intent=%s", state.session_id, intent.main_intent)
        payload["state"] = self.state_tracker_service.apply(state, intent)
        return payload

    def policy_layer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=policy_layer session=%s", state.session_id)
        payload["state"] = self.policy_service.decide(state)
        logger.debug("node=policy_layer decision action=%s", state.current_action)
        return payload

    def route_after_policy(self, payload: dict[str, Any]) -> str:
        state: ConversationState = payload["state"]
        action = state.current_action
        if action in {"ask_intent_clarification", "ask_slot_clarification"}:
            logger.debug("route_after_policy -> clarification_node session=%s", state.session_id)
            return "clarification_node"
        # agent_process 路由到 agent_node（工具调用）
        if action == "agent_process":
            logger.debug("route_after_policy -> agent_node session=%s", state.session_id)
            return "agent_node"
        if action == "handoff_human":
            logger.debug("route_after_policy -> handoff_node session=%s", state.session_id)
            return "handoff_node"
        # 其他情况（如 answer_directly）路由到 response_generator
        logger.debug("route_after_policy -> response_generator session=%s", state.session_id)
        return "response_generator"

    def clarification_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=clarification_node session=%s", state.session_id)
        payload["state"] = self.clarification_service.generate(state)
        return payload

    def agent_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=agent_node session=%s", state.session_id)
        payload["state"] = self.agent_node_service.run(state)
        return payload

    # knowledge_retriever 已移除，功能由 agent_node 里的 rag_retrieve 工具替代
        state: ConversationState = payload["state"]
        logger.debug("node=knowledge_retriever session=%s", state.session_id)
        payload["state"] = self.rag_retrieval_service.retrieve(state)
        return payload

    def business_tool_executor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=business_tool_executor session=%s", state.session_id)
        payload["state"] = self.execution_service.execute_business_tool(state)
        logger.info("tool_result session=%s result=%s", state.session_id, state.tool_result)
        return payload

    def handoff_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.info("node=handoff_node session=%s reason=%s", state.session_id, state.handoff_reason)
        payload["state"] = self.execution_service.create_handoff(state)
        return payload

    def response_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=response_generator session=%s", state.session_id)
        payload["state"] = self.response_service.generate(state)
        logger.debug("response=%r session=%s", state.reply[:80] if state.reply else "", state.session_id)
        return payload

    def context_compressor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=context_compressor session=%s", state.session_id)
        payload["state"] = self.context_service.compress(state)
        return payload

    def memory_writer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]
        logger.debug("node=memory_writer session=%s", state.session_id)
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
