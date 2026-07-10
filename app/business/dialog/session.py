"""会话业务服务。

封装 dao 层的 ``SessionStore``，作为 api / agent 访问会话数据的统一入口。
存储实现（内存 / MySQL）仍由 ``SessionStore`` 负责；本模块只做业务层编排，
避免上层直接依赖数据访问细节。
"""

from __future__ import annotations

from typing import Any

from app.dao import SessionStore, get_session_store
from app.schema import ConversationState


class SessionService:
    """会话服务：委托 ``SessionStore`` 完成读写，对上层暴露稳定接口。"""

    def __init__(self, store: SessionStore | None = None) -> None:
        self._store = store or get_session_store()

    # ---- 状态读写（供 agent / dialog 内部使用，方法名对齐 SessionStore）----

    def get(self, session_id: str) -> ConversationState | None:
        return self._store.get(session_id)

    def save(self, state: ConversationState) -> ConversationState:
        return self._store.save(state)

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        self._store.append_message(session_id, role, content, message_type, sanitized_content)

    # ---- 会话管理（供 api 端点使用）----

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        return self._store.list_sessions(user_id)

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self._store.get_messages(session_id)

    def get_owner(self, session_id: str) -> int | None:
        """获取会话归属的 user_id，不存在返回 None。"""
        return self._store.get_user_id(session_id)

    def rename(self, session_id: str, title: str) -> None:
        self._store.update_title(session_id, title)

    def delete(self, session_id: str) -> None:
        self._store.delete_session(session_id)

    def create(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        return self._store.create_session(user_id, channel, title)


def get_session_service() -> SessionService:
    """构造默认实现的会话服务（按配置选择内存 / MySQL 存储）。"""
    return SessionService(get_session_store())
