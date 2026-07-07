from __future__ import annotations

from pathlib import Path

from app.models import ChatRequest, ConversationState
from app.store import SessionStore
from app.utils import build_action_record, load_yaml_file


DEFAULT_CLARIFICATION_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "clarification_prompts.yml"
)


class ClarificationPromptRegistry:
    def __init__(self, prompt_path: Path | None = None) -> None:
        self.prompt_path = prompt_path or DEFAULT_CLARIFICATION_PROMPT_PATH
        self._prompts = self._load()

    def get(self) -> dict:
        return self._prompts

    def _load(self) -> dict:
        data = load_yaml_file(self.prompt_path)
        prompts = data.get("clarification_prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError(f"Invalid clarification prompt config: {self.prompt_path}")
        return prompts


class ClarificationService:
    def __init__(self, prompt_registry: ClarificationPromptRegistry | None = None) -> None:
        self.prompt_registry = prompt_registry or ClarificationPromptRegistry()

    def generate(self, state: ConversationState) -> ConversationState:
        prompts = self.prompt_registry.get()
        if state.current_action == "ask_intent_clarification":
            state.reply = prompts["intent_clarification"]
        elif "order_id" in state.missing_slots:
            state.reply = prompts.get("slot_clarification", {}).get(
                state.current_main_intent,
                prompts["generic_slot_clarification"],
            )
        else:
            state.reply = prompts["generic_fallback"]
        state.latest_action_name = "clarification_node"
        state.latest_action_result = {"reply": state.reply}
        state.action_history.append(build_action_record("clarification_node", state.reply))
        return state


class ResponseService:
    def generate(self, state: ConversationState) -> ConversationState:
        if state.reply:
            return state

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
            state.action_history.append(build_action_record("response_generator", state.reply))
        return state


class MemoryService:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def persist(self, state: ConversationState, request: ChatRequest) -> ConversationState:
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
                tool_category=_tool_category(state),
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
                state_snapshot={
                    "current_main_intent": state.current_main_intent,
                    "current_sub_intent": state.current_sub_intent,
                    "stage": state.stage,
                    "slots": state.slots,
                    "missing_slots": state.missing_slots,
                    "summary": state.summary,
                },
            )

        self.store.save(state)
        return state


def _tool_category(state: ConversationState) -> str:
    if state.current_action == "retrieve_knowledge":
        return "retrieval"
    if state.current_action == "handoff_human":
        return "workflow"
    return "query"
