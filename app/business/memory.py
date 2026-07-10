from __future__ import annotations

from app.schema import ChatRequest, ConversationState
from app.dao import SessionStore


def _tool_category(state: ConversationState) -> str:
    if state.current_action == "handoff_human":
        return "workflow"
    return "query"


class MessageService:
    """对话记忆持久化：把用户消息、助手回复、工具调用写入 SessionStore。"""

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

        self.store.save(state)
        return state
