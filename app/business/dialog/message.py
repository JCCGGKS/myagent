from __future__ import annotations

from app.schema import ChatRequest, ConversationState

from app.business.dialog.session import SessionService


class MessageService:
    """对话消息持久化：把用户消息、助手回复写入会话存储。"""

    def __init__(self, store: SessionService) -> None:
        self.store = store

    async def persist(self, state: ConversationState, request: ChatRequest) -> ConversationState:
        # SessionService / SessionStore 在 M2 已为原生异步（AsyncSession），
        # 这里直接 await 即可，I/O 等待时让出事件循环，不会阻塞其它请求。
        await self.store.append_message(state.session_id, "user", request.message)
        await self.store.append_message(
            state.session_id,
            "assistant",
            state.reply,
            "clarification" if state.current_action.startswith("ask_") else "text",
        )
        await self.store.save(state)
        return state
