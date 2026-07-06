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


INTENT_REQUIRED_SLOTS = {
    "query_order": ["order_id"],
    "query_logistics": ["order_id"],
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

        state: ConversationState = result["state"]
        state.message_history.append({"role": "assistant", "content": state.reply})
        self.store.save(state)
        return ChatResponse(
            reply=state.reply,
            intent=state.current_intent,
            stage=state.stage,
            needs_clarification=state.needs_clarification,
            handoff=state.handoff,
            slots=state.slots,
        )

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
        previous_intent = state.current_intent
        faq = self.knowledge_base.search(message)

        has_handoff_keyword = any(token in lowered for token in ["转人工", "人工客服"])
        has_logistics_keyword = any(token in lowered for token in ["物流", "快递", "配送"])
        has_order_keyword = any(
            token in lowered for token in ["查订单", "订单", "订单状态", "发货了吗", "我的订单"]
        )

        if has_handoff_keyword:
            intent = IntentResult(
                intent="handoff_human",
                confidence=0.99,
                route_source="rule",
            )
        elif has_logistics_keyword:
            slots = {"order_id": order_id} if order_id else {}
            intent = IntentResult(
                intent="query_logistics",
                confidence=0.92 if order_id else 0.78,
                slots=slots,
                route_source="rule",
                needs_clarification=order_id is None,
            )
        elif faq and not has_order_keyword:
            intent = IntentResult(
                intent="faq",
                confidence=0.8,
                route_source="faq_match",
                candidate_intents=["faq"],
            )
        elif has_order_keyword:
            slots = {"order_id": order_id} if order_id else {}
            intent = IntentResult(
                intent="query_order",
                confidence=0.9 if order_id else 0.76,
                slots=slots,
                route_source="rule",
                needs_clarification=order_id is None,
            )
        elif order_id and previous_intent in {"query_order", "query_logistics"}:
            intent = IntentResult(
                intent=previous_intent,
                confidence=0.88,
                slots={"order_id": order_id},
                route_source="slot_followup",
            )
        elif faq:
            intent = IntentResult(
                intent="faq",
                confidence=0.8,
                route_source="faq_match",
                candidate_intents=["faq"],
            )
        else:
            intent = IntentResult(
                intent="unsupported",
                confidence=0.2,
                route_source="fallback",
                needs_clarification=True,
            )

        intent.is_intent_shift = previous_intent not in {"unsupported", intent.intent}
        state.intent_result = intent
        payload["state"] = state
        return payload

    def state_tracker(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        intent = state.intent_result
        if intent is None:
            return payload

        if intent.intent != "unsupported":
            state.current_intent = intent.intent
        state.slots.update(intent.slots)
        state.risk_level = intent.risk_level
        state.needs_clarification = intent.needs_clarification
        state.handoff = intent.intent == "handoff_human"

        required_slots = INTENT_REQUIRED_SLOTS.get(state.current_intent, [])
        state.missing_slots = [slot for slot in required_slots if not state.slots.get(slot)]

        if state.handoff:
            state.stage = "handoff"
            state.needs_clarification = False
        elif state.missing_slots:
            state.stage = "collecting_info"
            state.needs_clarification = True
        elif state.current_intent in {"query_order", "query_logistics"}:
            state.stage = "executing"
        elif state.current_intent == "faq":
            state.stage = "responding"
        else:
            state.stage = "unsupported"

        summary_bits = [f"intent={state.current_intent}"]
        if state.slots:
            summary_bits.append(f"slots={state.slots}")
        state.summary = "; ".join(summary_bits)
        payload["state"] = state
        return payload

    def route_after_tracking(self, payload: dict[str, Any]) -> str:
        state: ConversationState = payload["state"]
        if state.current_intent == "handoff_human":
            return "handoff_handler"
        if state.needs_clarification:
            return "clarification_handler"
        if state.current_intent == "faq":
            return "faq_retriever"
        if state.current_intent in {"query_order", "query_logistics"}:
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

        if state.current_intent == "query_order":
            order = self.order_service.get_order_status(order_id)
            state.tool_result = {"kind": "order", "data": order.model_dump() if order else None}
        elif state.current_intent == "query_logistics":
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
            if state.current_intent == "query_logistics":
                state.reply = "请提供订单号，我来帮你查询物流进度。"
            elif state.current_intent == "query_order":
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

        if state.current_intent == "faq" and state.retrieved_faq:
            state.reply = state.retrieved_faq["answer"]
        elif state.current_intent == "query_order":
            order = (state.tool_result or {}).get("data")
            if order:
                state.reply = (
                    f"订单 {order['order_id']} 当前状态为 {order['status']}，"
                    f"商品是 {order['product_name']}，金额 {order['amount']} 元。"
                )
            else:
                state.reply = "没有查到这个订单号，请确认后重试，或者我可以帮你转人工。"
        elif state.current_intent == "query_logistics":
            logistics = (state.tool_result or {}).get("data")
            if logistics:
                latest = logistics["timeline"][-1]
                state.reply = (
                    f"订单 {logistics['order_id']} 当前物流状态为 {logistics['tracking_status']}，"
                    f"最近一条记录是 {latest['time']} {latest['status']}。"
                )
            else:
                state.reply = "没有查到该订单的物流信息，请确认订单号是否正确。"
        elif state.current_intent == "handoff_human":
            handoff = (state.tool_result or {}).get("data", {})
            state.reply = (
                f"已为你转人工客服，服务单号 {handoff.get('ticket_id', 'N/A')}。"
                "人工客服会基于当前会话上下文继续处理。"
            )
        else:
            state.reply = "这个问题我暂时无法准确处理。你可以换一种说法，或者我可以帮你转人工。"

        payload["state"] = state
        return payload
