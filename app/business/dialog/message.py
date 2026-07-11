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

    async def persist_user_message(self, state: ConversationState, request: ChatRequest) -> None:
        """尽早落库用户消息：请求处理中刷新页面，用户刚发送的内容也不会丢失。

        必须在「构建图输入 payload」之后、运行图之前调用，以保证图内
        in-memory 上下文不会把已落库的用户消息重复加载进来。
        """
        await self.store.append_message(state.session_id, "user", request.message)
        await self.store.save(state)

    async def persist_assistant_reply(self, state: ConversationState, request: ChatRequest) -> None:
        """落库助手回复（图运行结束后调用），确保回复先持久化再下发 final 事件。"""
        await self.store.append_message(
            state.session_id,
            "assistant",
            state.reply,
            "clarification" if state.current_action.startswith("ask_") else "text",
        )
        await self.store.save(state)
