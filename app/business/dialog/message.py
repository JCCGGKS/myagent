from __future__ import annotations

from app.schema import ChatRequest, ConversationState

from app.business.dialog.session import SessionService


class MessageService:
    """对话消息持久化：把用户消息、助手回复写入会话存储。"""

    def __init__(self, store: SessionService) -> None:
        self.store = store

    def persist(self, state: ConversationState, request: ChatRequest) -> ConversationState:
        self.store.append_message(state.session_id, "user", request.message)
        self.store.append_message(
            state.session_id,
            "assistant",
            state.reply,
            message_type="clarification" if state.current_action.startswith("ask_") else "text",
        )

        self.store.save(state)
        return state
