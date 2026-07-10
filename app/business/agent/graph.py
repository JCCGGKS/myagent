from __future__ import annotations

import logging
from typing import Any, Callable

from app.schema import ChatRequest, ChatResponse, ConversationState, ToolExecutionResult

logger = logging.getLogger(__name__)
from app.business.agent.agent_node import AgentNodeService
from app.business.tools.tool_executor import ToolExecutor
from app.business import (
    ClarificationService,
    ContextService,
    HandoffClarificationPolicy,
    HandoffService,
    IntentRouterService,
    IntentSchemaRegistry,
    LLMIntentFallbackService,
    LogisticsService,
    MessageService,
    OrderService,
    ResponseService,
    StateTrackerService,
)
from app.dao import SessionStore
from app.config.context_config import get_context_config_service
from app.utils import normalize_whitespace

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "END"
    START = "START"
    StateGraph = None


def _make_summary_fold_fn(
    llm_client: Any | None,
    llm_model: str | None,
) -> Callable[[str, list[dict]], str] | None:
    """构造摘要折叠器：把已有摘要与新增溢出消息合并为一段连贯摘要。

    无 LLM 客户端时返回 None，由 ContextService 退化为拼接截断。
    """

    def fold(old_summary: str, overflow: list[dict]) -> str:
        new_text = "\n".join(
            f"{m.get('role', '')}: {m.get('content', '')}"
            for m in overflow
            if m.get("content")
        )
        messages = [
            {
                "role": "system",
                "content": "你负责压缩客服对话，输出简洁中文摘要，保留关键实体与未决问题。",
            },
            {
                "role": "user",
                "content": (
                    "请把「已有摘要」与「新增对话片段」合并为一段连贯摘要，"
                    "保留用户意图、订单号/物流单号等关键实体、已解决与未解决的问题；"
                    "不要逐条罗列，不要编造新信息。\n\n"
                    f"已有摘要：\n{old_summary or '(无)'}\n\n"
                    f"新增对话片段：\n{new_text}"
                ),
            },
        ]
        try:
            resp = llm_client.chat.completions.create(model=llm_model, messages=messages)
            summary = resp.choices[0].message.content or ""
            return summary.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("summary fold LLM call failed err=%r", exc)
            return ""

    if llm_client is None or not llm_model:
        return None
    return fold


class CustomerServiceAgent:
    def __init__(
        self,
        store: SessionStore,
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
        llm_fallback_service: LLMIntentFallbackService | None = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
    ) -> None:
        self.store = store
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.intent_schema_registry = IntentSchemaRegistry()
        self.intent_router_service = IntentRouterService(llm_fallback_service=llm_fallback_service)
        self.state_tracker_service = StateTrackerService(schema_registry=self.intent_schema_registry)
        self.policy_service = HandoffClarificationPolicy()
        self.clarification_service = ClarificationService(
            llm_client=llm_client,
            llm_model=llm_model,
        )
        context_config = get_context_config_service().get_config()
        self.context_service = ContextService(
            state_tracker=self.state_tracker_service,
            max_recent_messages=context_config.max_recent_messages,
            max_summary_chars=context_config.max_summary_chars,
            summarizer=_make_summary_fold_fn(llm_client, llm_model),
        )
        self.response_service = ResponseService(
            llm_client=llm_client,
            llm_model=llm_model,
        )
        self.message_service = MessageService(store)
        # 统一工具执行服务（覆盖 LLM 函数调用工具与业务工具）
        self.tool_executor = ToolExecutor(
            order_service=order_service,
            logistics_service=logistics_service,
            handoff_service=handoff_service,
        )
        # agent_node 初始化（工具编排节点）
        self.agent_node_service = AgentNodeService(
            llm_client=llm_client,
            llm_model=llm_model,
            tool_executor=self.tool_executor,
            tools=None,  # 会从默认工具列表加载
        )
        # langgraph 为硬依赖：不可用时显式报错
        if StateGraph is None:
            raise RuntimeError(
                "LangGraph is required for agent orchestration; please install langgraph."
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
        builder.add_node("agent_node", self.agent_node)
        builder.add_node("handoff_node", self.handoff_node)
        builder.add_node("response_generator", self.response_generator)
        builder.add_node("context_compressor", self.context_compressor)
        builder.add_node("message_writer", self.message_writer)

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
        builder.add_edge("context_compressor", "message_writer")
        builder.add_edge("message_writer", END)
        return builder.compile()

    def chat(self, request: ChatRequest, user_id: int) -> ChatResponse:
        logger.info("chat start session=%s user=%s message=%r", request.session_id, user_id, request.message[:80])
        state = self._execute_request(request, user_id)
        logger.info(
            "chat done session=%s user=%s intent=%s.%s action=%s",
            request.session_id, user_id,
            state.current_main_intent, state.current_sub_intent, state.current_action,
        )
        return self._build_chat_response(state)

    def chat_events(self, request: ChatRequest, user_id: int) -> list[dict[str, Any]]:
        """LangGraph 图驱动的事件生成（与 chat() 行为一致）。"""
        payload = self._build_payload(request, user_id)
        events: list[dict[str, Any]] = []
        for chunk in self.graph.stream(payload):
            for node_name, node_payload in chunk.items():
                # node_payload is the full payload dict: {"state": ..., "request": ...}
                state = node_payload.get("state") if isinstance(node_payload, dict) else node_payload
                if state:
                    events.extend(self._node_state_to_events(node_name, state))
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
        elif node_name in {"handoff_node", "agent_node"}:
            if state.tool_result:
                events.append({"type": "tool_result", "tool_result": self._serialize_tool_result(state)})
        elif node_name == "response_generator":
            events.append({"type": "final", "response": self._build_chat_response(state).model_dump()})
        # 其他节点不推事件（或推通用 trace）
        return events

    def _execute_request(self, request: ChatRequest, user_id: int) -> ConversationState:
        payload = self._build_payload(request, user_id)
        payload = self.graph.invoke(payload)
        return payload["state"]

    def _build_payload(self, request: ChatRequest, user_id: int) -> dict[str, Any]:
        state = self.store.get(request.session_id) or ConversationState(
            session_id=request.session_id,
            user_id=user_id,
            channel=request.channel,
        )
        return {"state": state, "request": request}

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
        # state.user_id 已在 _build_payload 初始化时设置
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

    def handoff_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.info("node=handoff_node session=%s reason=%s", state.session_id, state.handoff_reason)
        payload["state"] = self.tool_executor.create_handoff(state)
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

    def message_writer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]
        logger.debug("node=message_writer session=%s", state.session_id)
        payload["state"] = self.message_service.persist(state, request)
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
            "reply": state.reply,
            "archived_states": state.archived_states,
        }

    def _build_turn_trace(self, state: ConversationState) -> list[str]:
        trace = [
            f"识别主意图: {state.current_main_intent}",
            f"识别子意图: {state.current_sub_intent}",
            f"当前阶段: {state.stage}",
            f"策略动作: {state.current_action}",
            f"情绪: {state.emotion.primary}",
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
