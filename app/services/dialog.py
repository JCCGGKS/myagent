from __future__ import annotations

from pathlib import Path

from app.models import ChatRequest, ConversationState
from app.store import SessionStore
from app.utils import build_action_record, load_yaml_file


DEFAULT_CLARIFICATION_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "clarification_prompts.yml"
)
DEFAULT_RESPONSE_PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "response_prompts.yml"


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


class ResponsePromptRegistry:
    def __init__(self, prompt_path: Path | None = None) -> None:
        self.prompt_path = prompt_path or DEFAULT_RESPONSE_PROMPT_PATH
        self._prompts = self._load()

    def get(self) -> dict:
        return self._prompts

    def _load(self) -> dict:
        data = load_yaml_file(self.prompt_path)
        prompts = data.get("response_prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError(f"Invalid response prompt config: {self.prompt_path}")
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
    def __init__(self, prompt_registry: ResponsePromptRegistry | None = None) -> None:
        self.prompt_registry = prompt_registry or ResponsePromptRegistry()

    def generate(self, state: ConversationState) -> ConversationState:
        prompts = self.prompt_registry.get()
        if state.reply:
            return state

        if state.current_main_intent == "complaint":
            state.reply = prompts.get("complaint_ack", "非常抱歉给你带来不好的体验。")
        elif state.current_sub_intent == "after_sale_refund.consult_policy":
            state.reply = (
                state.tool_result.user_facing_summary
                if state.tool_result and state.tool_result.user_facing_summary
                else prompts["refund_policy_fallback"]
            )
        elif state.current_sub_intent == "after_sale_refund.request_refund":
            state.reply = prompts["refund_request_ack"]
        elif state.current_sub_intent == "order_query.query_status":
            tool_data = state.tool_result.sanitized_result if state.tool_result else None
            if tool_data:
                state.reply = prompts["order_template"].format(
                    order_id=tool_data["order_id"],
                    status=tool_data["status"],
                    product_name=tool_data["product_name"],
                    amount=tool_data["amount"],
                )
            else:
                state.reply = prompts["order_not_found"]
        elif state.current_sub_intent == "logistics.not_received":
            tool_data = state.tool_result.sanitized_result if state.tool_result else None
            if tool_data and tool_data.get("timeline"):
                latest = tool_data["timeline"][-1]
                state.reply = prompts["logistics_template"].format(
                    order_id=tool_data["order_id"],
                    tracking_status=tool_data["tracking_status"],
                    latest_time=latest["time"],
                    latest_status=latest["status"],
                )
            else:
                state.reply = prompts["logistics_not_found"]
        elif state.current_main_intent == "handoff_service":
            handoff_data = state.tool_result.sanitized_result if state.tool_result else {}
            state.reply = prompts["handoff_template"].format(
                ticket_id=handoff_data.get("ticket_id", "N/A")
            )
        elif state.current_sub_intent == "chitchat.greeting":
            state.reply = prompts["greeting"]
        elif state.current_main_intent == "unsupported_biz":
            state.reply = prompts["unsupported_biz"]
        else:
            state.reply = prompts["unknown_fallback"]

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
    if state.current_action == "handoff_human":
        return "workflow"
    return "query"
