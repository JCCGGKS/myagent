from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable
from typing import Any, Callable

from app.schema import ChatRequest, ChatResponse, ConversationState

logger = logging.getLogger(__name__)
from app.business.agent.agent_node import AgentNodeService
from app.business.tools.tool_executor import ToolExecutor
from app.business.tools.registry import build_tool_schemas
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
from app.business.dialog import SessionService
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
) -> Callable[[str, list[dict]], Awaitable[str]] | None:
    """构造摘要折叠器（异步）：把已有摘要与新增溢出消息合并为一段连贯摘要。

    无 LLM 客户端时返回 None，由 ContextService 退化为拼接截断。
    """

    async def fold(old_summary: str, overflow: list[dict]) -> str:
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
            resp = await llm_client.chat.completions.create(model=llm_model, messages=messages)
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
        store: SessionService,
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
            tools=build_tool_schemas(),  # 注册全部工具 schema 到 LLM function calling
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
        builder.add_edge("context_compressor", END)
        return builder.compile()

    async def chat(self, request: ChatRequest, user_id: int) -> ChatResponse:
        logger.info("chat start session=%s user=%s message=%r", request.session_id, user_id, request.message[:80])
        state = await self._execute_request(request, user_id)
        # 边界落库：图运行期间只收集数据，结束后批量写入会话存储
        state = await self.message_service.persist(state, request)
        logger.info(
            "chat done session=%s user=%s intent=%s.%s action=%s",
            request.session_id, user_id,
            state.current_main_intent, state.current_sub_intent, state.current_action,
        )
        return self._build_chat_response(state)

    async def chat_events(self, request: ChatRequest, user_id: int) -> "AsyncGenerator[dict[str, Any], None]":
        """LangGraph 图驱动的事件生成（与 chat() 行为一致，异步生成器）。

        使用 ``graph.astream`` 按节点分块产出事件，I/O 等待时让出事件循环，
        避免单请求阻塞整个事件循环（详见 plans/full-async-plan.md）。

        落库顺序：图运行期间实时下发 intent/state/tool_result 等事件；
        **final 事件在落库之后才下发**——先 ``persist``（用户消息 + 助手回复 +
        状态快照）再 yield ``final``，避免「客户端已收到回复但 DB 尚未落库」的
        窗口（进程在二者间崩溃会导致上下文丢失）。若图未走到 response_generator
        （如澄清分支）则不产生 final 事件，落库仍照常进行。
        """
        payload = await self._build_payload(request, user_id)
        final_state: ConversationState | None = None
        async for chunk in self.graph.astream(payload):
            for node_name, node_payload in chunk.items():
                # node_payload is the full payload dict: {"state": ..., "request": ...}
                state = node_payload.get("state") if isinstance(node_payload, dict) else node_payload
                if state:
                    final_state = state
                    for ev in self._node_state_to_events(node_name, state):
                        # final 需先落库再下发，故此处暂不下发，留待落库后统一 yield
                        if ev.get("type") == "final":
                            continue
                        yield ev
        # 边界落库：先持久化（用户消息 + 助手回复 + 状态快照），再下发 final 事件。
        if final_state is not None:
            await self.message_service.persist(final_state, request)
            yield {"type": "final", "response": self._build_chat_response(final_state).model_dump()}

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

    async def _execute_request(self, request: ChatRequest, user_id: int) -> ConversationState:
        payload = await self._build_payload(request, user_id)
        payload = await self.graph.ainvoke(payload)
        return payload["state"]

    async def _build_payload(self, request: ChatRequest, user_id: int) -> dict[str, Any]:
        # 注意括号：先 await，再做 or 默认构造，避免 await 作用于整个 or 表达式
        state = (await self.store.get(request.session_id)) or ConversationState(
            session_id=request.session_id,
            user_id=user_id,
            channel=request.channel,
        )
        return {"state": state, "request": request}

    async def input_normalizer(self, payload: dict[str, Any]) -> dict[str, Any]:
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

        state.channel = request.channel
        # state.user_id 已在 _build_payload 初始化时设置
        state.recent_messages.append({"role": "user", "content": message})
        payload["state"] = state
        return payload

    async def intent_router(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=intent_router session=%s", state.session_id)
        state.intent_result = await self.intent_router_service.route(
            state, state.recent_messages[-1]["content"]
        )
        logger.debug(
            "node=intent_router result intent=%s.%s source=%s",
            state.intent_result.main_intent if state.intent_result else None,
            state.intent_result.sub_intent if state.intent_result else None,
            state.intent_result.route_source if state.intent_result else None,
        )
        payload["state"] = state
        return payload

    async def state_tracker(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        intent = state.intent_result
        if intent is None:
            logger.warning("state_tracker: no intent_result session=%s", state.session_id)
            return payload
        logger.debug("node=state_tracker session=%s intent=%s", state.session_id, intent.main_intent)
        payload["state"] = self.state_tracker_service.apply(state, intent)
        return payload

    async def policy_layer(self, payload: dict[str, Any]) -> dict[str, Any]:
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

    async def clarification_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=clarification_node session=%s", state.session_id)
        payload["state"] = await self.clarification_service.generate(state)
        return payload

    async def agent_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=agent_node session=%s", state.session_id)
        payload["state"] = await self.agent_node_service.run(state)
        return payload

    async def handoff_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.info("node=handoff_node session=%s reason=%s", state.session_id, state.handoff_reason)
        payload["state"] = self.tool_executor.create_handoff(state)
        return payload

    async def response_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=response_generator session=%s", state.session_id)
        payload["state"] = await self.response_service.generate(state)
        logger.debug("response=%r session=%s", state.reply[:80] if state.reply else "", state.session_id)
        return payload

    async def context_compressor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug("node=context_compressor session=%s", state.session_id)
        payload["state"] = await self.context_service.compress(state)
        return payload

    def _build_chat_response(self, state: ConversationState) -> ChatResponse:
        # 简化后只下发前端真正渲染的字段：reply（消息气泡）+ session_state（StatsPanel）。
        # 其余意图/槽位/阶段等均在 session_state 内部，无需在顶层重复。
        return ChatResponse(
            reply=state.reply,
            session_state=self._build_session_snapshot(state),
        )

    def _build_session_snapshot(self, state: ConversationState) -> dict[str, Any]:
        # 仅下发 StatsPanel（经 sessionSnapshot）实际消费的字段，其余内部状态不进响应，
        # 避免冗余 payload（详见前端 ConsoleView / StatsPanel）。
        return {
            "current_main_intent": state.current_main_intent,
            "current_sub_intent": state.current_sub_intent,
            "stage": state.stage,
            "slots": state.slots,
            "missing_slots": state.missing_slots,
            "needs_clarification": state.needs_clarification,
            "summary": state.summary,
        }

    def _serialize_tool_result(self, state: ConversationState) -> dict[str, Any] | None:
        return state.tool_result.model_dump() if state.tool_result else None
