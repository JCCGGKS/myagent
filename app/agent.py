from __future__ import annotations

from typing import Any

from app.models import ChatRequest, ChatResponse, ConversationState, IntentResult
from app.services import (
    HandoffService,
    KnowledgeBaseService,
    LogisticsService,
    OrderService,
    extract_order_id,
)
from app.store import SessionStore

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "END"
    START = "START"
    StateGraph = None


SUB_INTENT_REQUIRED_SLOTS = {
    "order_service.query_status": ["order_id"],
    "logistics_service.query_status": ["order_id"],
}


class CustomerServiceAgent:
    def __init__(
        self,
        store: SessionStore,
        knowledge_base: KnowledgeBaseService,
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
    ) -> None:
        self.store = store
        self.knowledge_base = knowledge_base
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        if StateGraph is None:
            return None

        builder = StateGraph(dict)
        builder.add_node("input_normalizer", self.input_normalizer)
        builder.add_node("intent_router", self.intent_router)
        builder.add_node("state_tracker", self.state_tracker)
        builder.add_node("faq_retriever", self.faq_retriever)
        builder.add_node("business_tool_executor", self.business_tool_executor)
        builder.add_node("clarification_handler", self.clarification_handler)
        builder.add_node("handoff_handler", self.handoff_handler)
        builder.add_node("response_generator", self.response_generator)

        builder.add_edge(START, "input_normalizer")
        builder.add_edge("input_normalizer", "intent_router")
        builder.add_edge("intent_router", "state_tracker")
        builder.add_conditional_edges(
            "state_tracker",
            self.route_after_tracking,
            {
                "faq_retriever": "faq_retriever",
                "business_tool_executor": "business_tool_executor",
                "clarification_handler": "clarification_handler",
                "handoff_handler": "handoff_handler",
                "response_generator": "response_generator",
            },
        )
        builder.add_edge("faq_retriever", "response_generator")
        builder.add_edge("business_tool_executor", "response_generator")
        builder.add_edge("clarification_handler", "response_generator")
        builder.add_edge("handoff_handler", "response_generator")
        builder.add_edge("response_generator", END)
        return builder.compile()

    def chat(self, request: ChatRequest) -> ChatResponse:
        state = self._execute_request(request)
        return self._build_chat_response(state)

    def chat_events(self, request: ChatRequest) -> list[dict[str, Any]]:
        state = self.store.get(request.session_id) or ConversationState(
            session_id=request.session_id,
            user_id=request.user_id,
            channel=request.channel,
        )
        payload = {"state": state, "request": request}
        events: list[dict[str, Any]] = []

        payload = self.input_normalizer(payload)
        state = payload["state"]
        events.append(
            {
                "type": "status",
                "stage": "input_normalizer",
                "message": "已接收用户消息",
            }
        )

        payload = self.intent_router(payload)
        state = payload["state"]
        events.append(
            {
                "type": "intent",
                "main_intent": (
                    state.intent_result.main_intent if state.intent_result else "unsupported"
                ),
                "sub_intent": (
                    state.intent_result.sub_intent
                    if state.intent_result
                    else "unsupported.unknown"
                ),
                "confidence": state.intent_result.confidence if state.intent_result else 0.0,
                "slots": state.intent_result.slots if state.intent_result else {},
                "needs_clarification": (
                    state.intent_result.needs_clarification if state.intent_result else False
                ),
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

        route = self.route_after_tracking(payload)
        events.append(
            {
                "type": "trace",
                "message": f"路由到 {route}",
            }
        )

        if route == "faq_retriever":
            payload = self.faq_retriever(payload)
            events.append(
                {
                    "type": "trace",
                    "message": "已命中 FAQ 检索",
                }
            )
        elif route == "business_tool_executor":
            payload = self.business_tool_executor(payload)
            state = payload["state"]
            events.append(
                {
                    "type": "tool_result",
                    "tool_result": state.tool_result,
                }
            )
        elif route == "clarification_handler":
            payload = self.clarification_handler(payload)
            events.append(
                {
                    "type": "trace",
                    "message": "进入澄清追问流程",
                }
            )
        elif route == "handoff_handler":
            payload = self.handoff_handler(payload)
            state = payload["state"]
            events.append(
                {
                    "type": "tool_result",
                    "tool_result": state.tool_result,
                }
            )

        payload = self.response_generator(payload)
        state = self._finalize_state(payload["state"])
        events.append(
            {
                "type": "final",
                "response": self._build_chat_response(state).model_dump(),
            }
        )
        return events

    def _execute_request(self, request: ChatRequest) -> ConversationState:
        current_state = self.store.get(request.session_id) or ConversationState(
            session_id=request.session_id,
            user_id=request.user_id,
            channel=request.channel,
        )
        payload = {"state": current_state, "request": request}

        if self.graph is None:
            result = self._run_without_langgraph(payload)
        else:
            result = self.graph.invoke(payload)

        return self._finalize_state(result["state"])

    def _finalize_state(self, state: ConversationState) -> ConversationState:
        state.message_history.append({"role": "assistant", "content": state.reply})
        self.store.save(state)
        return state

    def _build_chat_response(self, state: ConversationState) -> ChatResponse:
        turn_trace = self._build_turn_trace(state)
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
            tool_result=state.tool_result,
            session_state=self._build_session_snapshot(state),
            turn_trace=turn_trace,
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
            "needs_clarification": state.needs_clarification,
            "handoff": state.handoff,
            "summary": state.summary,
            "risk_level": state.risk_level,
            "last_user_message": state.last_user_message,
            "message_history": state.message_history,
            "reply": state.reply,
        }

    def _build_turn_trace(self, state: ConversationState) -> list[str]:
        trace = [
            f"识别主意图: {state.current_main_intent}",
            f"识别子意图: {state.current_sub_intent}",
            f"当前阶段: {state.stage}",
        ]
        if state.slots:
            trace.append(f"已填槽位: {state.slots}")
        if state.missing_slots:
            trace.append(f"缺失槽位: {state.missing_slots}")
        if state.tool_result:
            trace.append(f"工具调用结果: {state.tool_result.get('kind', 'unknown')}")
        if state.handoff:
            trace.append("触发转人工流程")
        if state.needs_clarification:
            trace.append("需要继续追问补齐信息")
        return trace

    def _run_without_langgraph(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self.input_normalizer(payload)
        payload = self.intent_router(payload)
        payload = self.state_tracker(payload)
        route = self.route_after_tracking(payload)
        if route == "faq_retriever":
            payload = self.faq_retriever(payload)
        elif route == "business_tool_executor":
            payload = self.business_tool_executor(payload)
        elif route == "clarification_handler":
            payload = self.clarification_handler(payload)
        elif route == "handoff_handler":
            payload = self.handoff_handler(payload)
        payload = self.response_generator(payload)
        return payload

    def input_normalizer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]
        message = " ".join(request.message.strip().split())

        # Reset per-turn transient fields so the current request cannot reuse
        # the previous turn's reply or intermediate results.
        state.reply = ""
        state.intent_result = None
        state.retrieved_faq = None
        state.tool_result = None
        state.handoff = False
        state.needs_clarification = False

        state.last_user_message = message
        state.channel = request.channel
        state.user_id = request.user_id
        state.message_history.append({"role": "user", "content": message})
        payload["state"] = state
        return payload

    def intent_router(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        message = state.last_user_message
        lowered = message.casefold()
        order_id = extract_order_id(message)
        previous_sub_intent = state.current_sub_intent
        faq = self.knowledge_base.search(message)

        has_handoff_keyword = any(token in lowered for token in ["转人工", "人工客服"])
        has_logistics_keyword = any(token in lowered for token in ["物流", "快递", "配送"])
        has_order_keyword = any(
            token in lowered for token in ["查订单", "订单", "订单状态", "发货了吗", "我的订单"]
        )
        has_greeting_keyword = any(
            token in lowered for token in ["你好", "您好", "hi", "hello", "在吗"]
        )
        has_thanks_keyword = any(
            token in lowered for token in ["谢谢", "感谢", "辛苦了", "thanks", "thank you"]
        )

        if has_handoff_keyword:
            intent = IntentResult(
                main_intent="handoff_service",
                sub_intent="handoff_service.request_human",
                confidence=0.99,
                route_source="rule",
            )
        elif has_logistics_keyword:
            slots = {"order_id": order_id} if order_id else {}
            intent = IntentResult(
                main_intent="logistics_service",
                sub_intent="logistics_service.query_status",
                confidence=0.92 if order_id else 0.78,
                slots=slots,
                route_source="rule",
                needs_clarification=order_id is None,
            )
        elif has_greeting_keyword:
            intent = IntentResult(
                main_intent="chitchat",
                sub_intent="chitchat.greeting",
                confidence=0.95,
                route_source="rule",
            )
        elif has_thanks_keyword:
            intent = IntentResult(
                main_intent="chitchat",
                sub_intent="chitchat.thanks",
                confidence=0.95,
                route_source="rule",
            )
        elif faq:
            intent = IntentResult(
                main_intent="faq",
                sub_intent="faq.general",
                confidence=0.95,
                route_source="rule",
                candidate_intents=["faq"],
            )
        elif has_order_keyword:
            slots = {"order_id": order_id} if order_id else {}
            intent = IntentResult(
                main_intent="order_service",
                sub_intent="order_service.query_status",
                confidence=0.9 if order_id else 0.76,
                slots=slots,
                route_source="rule",
                needs_clarification=order_id is None,
            )
        elif order_id and previous_sub_intent in {
            "order_service.query_status",
            "logistics_service.query_status",
        }:
            main_intent = (
                "order_service"
                if previous_sub_intent == "order_service.query_status"
                else "logistics_service"
            )
            intent = IntentResult(
                main_intent=main_intent,
                sub_intent=previous_sub_intent,
                confidence=0.88,
                slots={"order_id": order_id},
                route_source="slot_followup",
            )
        else:
            intent = IntentResult(
                main_intent="unsupported",
                sub_intent="unsupported.unknown",
                confidence=0.2,
                route_source="fallback",
                needs_clarification=True,
            )

        intent.is_intent_shift = previous_sub_intent not in {
            "unsupported.unknown",
            intent.sub_intent,
        }
        state.intent_result = intent
        payload["state"] = state
        return payload

    def state_tracker(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        intent = state.intent_result
        if intent is None:
            return payload

        state.current_main_intent = intent.main_intent
        state.current_sub_intent = intent.sub_intent
        state.slots.update(intent.slots)
        state.risk_level = intent.risk_level
        state.needs_clarification = intent.needs_clarification
        state.handoff = intent.main_intent == "handoff_service"

        if state.current_main_intent == "unsupported":
            state.slots = {}

        required_slots = SUB_INTENT_REQUIRED_SLOTS.get(state.current_sub_intent, [])
        state.missing_slots = [slot for slot in required_slots if not state.slots.get(slot)]

        if state.handoff:
            state.stage = "handoff"
            state.needs_clarification = False
        elif state.missing_slots:
            state.stage = "collecting_info"
            state.needs_clarification = True
        elif state.current_main_intent in {"order_service", "logistics_service"}:
            state.stage = "executing"
        elif state.current_main_intent in {"faq", "chitchat"}:
            state.stage = "responding"
        else:
            state.stage = "unsupported"

        summary_bits = [
            f"main_intent={state.current_main_intent}",
            f"sub_intent={state.current_sub_intent}",
        ]
        if state.slots:
            summary_bits.append(f"slots={state.slots}")
        state.summary = "; ".join(summary_bits)
        payload["state"] = state
        return payload

    def route_after_tracking(self, payload: dict[str, Any]) -> str:
        state: ConversationState = payload["state"]
        if state.current_main_intent == "handoff_service":
            return "handoff_handler"
        if state.needs_clarification:
            return "clarification_handler"
        if state.current_main_intent == "faq":
            return "faq_retriever"
        if state.current_main_intent in {"order_service", "logistics_service"}:
            return "business_tool_executor"
        return "response_generator"

    def faq_retriever(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        state.retrieved_faq = self.knowledge_base.search(state.last_user_message)
        payload["state"] = state
        return payload

    def business_tool_executor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        order_id = state.slots["order_id"]

        if state.current_sub_intent == "order_service.query_status":
            order = self.order_service.get_order_status(order_id)
            state.tool_result = {"kind": "order", "data": order.model_dump() if order else None}
        elif state.current_sub_intent == "logistics_service.query_status":
            logistics = self.logistics_service.get_logistics(order_id)
            state.tool_result = {
                "kind": "logistics",
                "data": logistics.model_dump() if logistics else None,
            }
        payload["state"] = state
        return payload

    def clarification_handler(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        if "order_id" in state.missing_slots:
            if state.current_main_intent == "logistics_service":
                state.reply = "请提供订单号，我来帮你查询物流进度。"
            elif state.current_main_intent == "order_service":
                state.reply = "请提供订单号，我来帮你查询订单状态。"
            else:
                state.reply = "我还需要更多信息，麻烦补充一下你的问题。"
        else:
            state.reply = "我需要更多信息才能继续处理，或者可以为你转人工。"
        payload["state"] = state
        return payload

    def handoff_handler(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        handoff = self.handoff_service.create_handoff(state.session_id, state.summary)
        state.tool_result = {"kind": "handoff", "data": handoff.model_dump()}
        payload["state"] = state
        return payload

    def response_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        if state.reply:
            return payload

        if state.current_main_intent == "faq" and state.retrieved_faq:
            state.reply = state.retrieved_faq["answer"]
        elif state.current_sub_intent == "order_service.query_status":
            order = (state.tool_result or {}).get("data")
            if order:
                state.reply = (
                    f"订单 {order['order_id']} 当前状态为 {order['status']}，"
                    f"商品是 {order['product_name']}，金额 {order['amount']} 元。"
                )
            else:
                state.reply = "没有查到这个订单号，请确认后重试，或者我可以帮你转人工。"
        elif state.current_sub_intent == "logistics_service.query_status":
            logistics = (state.tool_result or {}).get("data")
            if logistics:
                latest = logistics["timeline"][-1]
                state.reply = (
                    f"订单 {logistics['order_id']} 当前物流状态为 {logistics['tracking_status']}，"
                    f"最近一条记录是 {latest['time']} {latest['status']}。"
                )
            else:
                state.reply = "没有查到该订单的物流信息，请确认订单号是否正确。"
        elif state.current_main_intent == "handoff_service":
            handoff = (state.tool_result or {}).get("data", {})
            state.reply = (
                f"已为你转人工客服，服务单号 {handoff.get('ticket_id', 'N/A')}。"
                "人工客服会基于当前会话上下文继续处理。"
            )
        elif state.current_sub_intent == "chitchat.greeting":
            state.reply = "你好，我可以帮你查询 FAQ、订单、物流，也可以为你转人工客服。"
        elif state.current_sub_intent == "chitchat.thanks":
            state.reply = "不客气。如果你还想查询订单、物流或退款问题，我可以继续帮你处理。"
        else:
            state.reply = "这个问题我暂时无法准确处理。你可以换一种说法，或者我可以帮你转人工。"

        payload["state"] = state
        return payload
