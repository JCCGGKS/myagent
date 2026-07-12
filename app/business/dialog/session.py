"""会话业务服务。

封装 dao 层的 ``SessionStore``，作为 api / agent 访问会话数据的统一入口。
存储实现（内存 / MySQL）仍由 ``SessionStore`` 负责；本模块只做业务层编排，
避免上层直接依赖数据访问细节。

M2 起 ``SessionStore`` 为原生异步（AsyncSession），本模块直接 ``await``，
不再需要 M1 的 ``asyncio.to_thread`` 线程桥接（详见 plans/full-async-plan.md）。
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

    async def get(self, session_id: str) -> ConversationState | None:
        return await self._store.get(session_id)

    async def ensure_session(self, session_id: str, user_id: int, channel: str = "web") -> None:
        """确保会话记录存在（登记归属 user_id）；不存在才创建、已存在不覆盖。

        用于聊天入口与会话管理接口（rename / get_messages / delete），
        保证未聊天、或聊天失败的会话也能被管理，不会因找不到会话而 404。
        """
        await self._store.ensure_session(session_id, user_id, channel)

    async def save(self, state: ConversationState) -> ConversationState:
        return await self._store.save(state)

    async def save_metadata(self, state: ConversationState) -> None:
        """仅更新会话元数据（user_id / channel / status），不持久化图态本身。

        图态由 checkpointer 接管后，agent 路径经 MessageService.persist 调此方法，
        避免把整个 ConversationState 再写回进程内存 / state 列。
        """
        await self._store.save_metadata(state)

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        await self._store.append_message(
            session_id, role, content, message_type, sanitized_content
        )

    # ---- 会话管理（供 api 端点使用）----

    async def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        return await self._store.list_sessions(user_id)

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return await self._store.get_messages(session_id)

    async def get_owner(self, session_id: str) -> int | None:
        """获取会话归属的 user_id，不存在返回 None。"""
        return await self._store.get_user_id(session_id)

    async def rename(self, session_id: str, title: str) -> None:
        await self._store.update_title(session_id, title)

    async def delete(self, session_id: str) -> None:
        await self._store.delete_session(session_id)

    async def create(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        return await self._store.create_session(user_id, channel, title)


def get_session_service() -> SessionService:
    """构造默认实现的会话服务（按配置选择内存 / MySQL 存储）。"""
    return SessionService(get_session_store())
