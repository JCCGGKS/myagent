from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update

from app.schema import ConversationState


logger = logging.getLogger(__name__)

# 会话状态枚举（sessions.status，TINYINT）
SESSION_STATUS_ACTIVE = 0
SESSION_STATUS_HANDOFF = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SessionStore(ABC):
    """会话存储接口（dao 层）。业务层只依赖此接口，实现可注入。

    M2 起所有方法均为 ``async def``，底层使用 ``AsyncSession``，I/O 等待时
    让出事件循环（详见 plans/full-async-plan.md）。内存实现同样为 async，仅逻辑同步。
    """

    @abstractmethod
    async def create_session(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        ...

    @abstractmethod
    async def get(self, session_id: str) -> ConversationState | None:
        ...

    @abstractmethod
    async def ensure_session(self, session_id: str, user_id: int, channel: str = "web") -> None:
        """确保会话记录存在（登记归属 user_id）；不存在才创建，已存在不覆盖。

        用于聊天入口与会话管理接口：即使后续未落库，会话也已登记，
        后续 rename / get_messages / delete 不会因找不到会话而 404。
        """

    @abstractmethod
    async def save(self, state: ConversationState) -> ConversationState:
        ...

    @abstractmethod
    async def save_metadata(self, state: ConversationState) -> None:
        """仅更新会话元数据（user_id / channel / status），不持久化图态本身。

        图态由 checkpointer（Redis / MemorySaver）接管后，agent 路径改调此方法，
        避免把整个 ConversationState 再写进进程内存字典或 state 列。
        """

    @abstractmethod
    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        """列出某用户的会话（含 title / updated_at），按 updated_at 倒序。"""

    @abstractmethod
    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """读取某会话的历史消息（role / content），按 sequence_no 正序。"""

    @abstractmethod
    async def get_user_id(self, session_id: str) -> int | None:
        """获取某会话的归属 user_id，不存在返回 None。"""

    @abstractmethod
    async def update_title(self, session_id: str, title: str) -> None:
        """更新会话名称。"""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """软删除会话（标记 deleted_at，保留数据与消息）。"""


class MemorySessionStore(SessionStore):
    """内存实现（本地/测试默认）。与原 app.store.SessionStore 行为一致。"""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    async def create_session(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = {
            "session": {
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
                "title": title,
                "status": SESSION_STATUS_ACTIVE,
                "created_at": _now(),
                "updated_at": _now(),
            },
            "messages": [],
            "state": None,
        }
        return session_id

    async def get(self, session_id: str) -> ConversationState | None:
        record = self._sessions.get(session_id)
        return deepcopy(record["state"]) if record else None

    async def ensure_session(self, session_id: str, user_id: int, channel: str = "web") -> None:
        if session_id in self._sessions:
            return
        self._sessions[session_id] = {
            "session": {
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
                "status": SESSION_STATUS_ACTIVE,
                "created_at": _now(),
                "updated_at": _now(),
            },
            "messages": [],
            "state": None,
        }

    async def save(self, state: ConversationState) -> ConversationState:
        record = self._sessions.setdefault(
            state.session_id,
            {
                "session": {
                    "session_id": state.session_id,
                    "user_id": state.user_id,
                    "channel": state.channel,
                    "status": SESSION_STATUS_ACTIVE,
                    "created_at": _now(),
                    "updated_at": _now(),
                },
                "messages": [],
                "state": None,
            },
        )
        record["state"] = deepcopy(state)
        record["session"].update(
            {
                "user_id": state.user_id,
                "channel": state.channel,
                "status": SESSION_STATUS_HANDOFF if state.handoff else SESSION_STATUS_ACTIVE,
                "updated_at": _now(),
            }
        )
        return state

    async def save_metadata(self, state: ConversationState) -> None:
        record = self._sessions.setdefault(
            state.session_id,
            {
                "session": {
                    "session_id": state.session_id,
                    "user_id": state.user_id,
                    "channel": state.channel,
                    "status": SESSION_STATUS_ACTIVE,
                    "created_at": _now(),
                    "updated_at": _now(),
                },
                "messages": [],
                "state": None,
            },
        )
        record["session"].update(
            {
                "user_id": state.user_id,
                "channel": state.channel,
                "status": SESSION_STATUS_HANDOFF if state.handoff else SESSION_STATUS_ACTIVE,
                "updated_at": _now(),
            }
        )

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        record = self._sessions.setdefault(
            session_id,
            {
                "session": {
                    "session_id": session_id,
                    "status": SESSION_STATUS_ACTIVE,
                    "created_at": _now(),
                    "updated_at": _now(),
                },
                "messages": [],
                "state": None,
            },
        )
        record["messages"].append(
            {
                "role": role,
                "message_type": message_type,
                "content": content,
                "sanitized_content": sanitized_content or content,
                "sequence_no": len(record["messages"]) + 1,
                "created_at": _now(),
            }
        )
        record["session"]["updated_at"] = _now()

    async def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        record = self._sessions.get(session_id)
        return deepcopy(record) if record else None

    async def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in self._sessions.values():
            session = record.get("session", {})
            if session.get("user_id") != user_id:
                continue
            if session.get("deleted_at") is not None:
                continue
            result.append(
                {
                    "session_id": session.get("session_id"),
                    "title": session.get("title", "新会话"),
                    "updated_at": session.get("updated_at"),
                }
            )
        result.sort(key=lambda s: str(s.get("updated_at") or ""), reverse=True)
        return result

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        record = self._sessions.get(session_id)
        if record is None:
            return []
        messages = record.get("messages", [])
        return [
            {
                "id": f"msg-{m['sequence_no']}",
                "role": m["role"],
                "content": m["content"],
                "sequence_no": m["sequence_no"],
            }
            for m in sorted(messages, key=lambda m: m.get("sequence_no", 0))
        ]

    async def get_user_id(self, session_id: str) -> int | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        return record.get("session", {}).get("user_id")

    async def update_title(self, session_id: str, title: str) -> None:
        record = self._sessions.get(session_id)
        if record is not None:
            record.setdefault("session", {})["title"] = title
            record["session"]["updated_at"] = _now()

    async def delete_session(self, session_id: str) -> None:
        record = self._sessions.get(session_id)
        if record is not None:
            record.setdefault("session", {})["deleted_at"] = _now()


class SqlSessionStore(SessionStore):
    """MySQL 实现（配置了 mysql 段且 aiomysql 可用时注入）。

    保留内存镜像以满足 get() 返回完整 ConversationState 的语义，
    同时把 sessions / messages 落库做会话持久化。M2 起底层为 AsyncSession。
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._states: dict[str, ConversationState] = {}

    def _db(self):
        return self._session_factory()

    async def create_session(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self._states[session_id] = None
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            db.add(
                SessionRow(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    title=title,
                    status=SESSION_STATUS_ACTIVE,
                )
            )
            await db.commit()
        return session_id

    async def get(self, session_id: str) -> ConversationState | None:
        state = self._states.get(session_id)
        return deepcopy(state) if state else None

    async def ensure_session(self, session_id: str, user_id: int, channel: str = "web") -> None:
        if session_id in self._states:
            return
        self._states[session_id] = None
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            row = (
                await db.execute(
                    select(SessionRow).where(SessionRow.session_id == session_id)
                )
            ).scalar_one_or_none()
            if row is None:
                db.add(
                    SessionRow(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        status=SESSION_STATUS_ACTIVE,
                    )
                )
                await db.commit()

    async def save(self, state: ConversationState) -> ConversationState:
        self._states[state.session_id] = deepcopy(state)
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            row = (
                await db.execute(
                    select(SessionRow).where(SessionRow.session_id == state.session_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = SessionRow(session_id=state.session_id)
                db.add(row)
            row.user_id = state.user_id
            row.channel = state.channel
            row.status = SESSION_STATUS_HANDOFF if state.handoff else SESSION_STATUS_ACTIVE
            await db.commit()
        return state

    async def save_metadata(self, state: ConversationState) -> None:
        # 仅更新 SessionRow 元数据；图态由 checkpointer 接管，不再写 _states。
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            row = (
                await db.execute(
                    select(SessionRow).where(SessionRow.session_id == state.session_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = SessionRow(session_id=state.session_id)
                db.add(row)
            row.user_id = state.user_id
            row.channel = state.channel
            row.status = SESSION_STATUS_HANDOFF if state.handoff else SESSION_STATUS_ACTIVE
            await db.commit()

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        async with self._db() as db:
            from app.model.session import Message, Session as SessionRow

            max_seq = (
                await db.execute(
                    select(func.coalesce(func.max(Message.sequence_no), 0)).where(
                        Message.session_id == session_id
                    )
                )
            ).scalar() or 0
            db.add(
                Message(
                    session_id=session_id,
                    role=role,
                    message_type=message_type,
                    content=content,
                    sanitized_content=sanitized_content or content,
                    sequence_no=max_seq + 1,
                )
            )
            await db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

    async def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        state = self._states.get(session_id)
        if state is None:
            return None
        return {"session_id": session_id, "state": deepcopy(state)}

    async def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            rows = (
                await db.execute(
                    select(
                        SessionRow.session_id,
                        SessionRow.title,
                        SessionRow.updated_at,
                    )
                    .where(SessionRow.user_id == user_id)
                    .where(SessionRow.deleted_at.is_(None))
                    .order_by(SessionRow.updated_at.desc())
                )
            ).all()
            return [
                {
                    "session_id": r.session_id,
                    "title": r.title,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        async with self._db() as db:
            from app.model.session import Message

            rows = (
                await db.execute(
                    select(Message.role, Message.content, Message.sequence_no)
                    .where(Message.session_id == session_id)
                    .order_by(Message.created_at.asc())
                )
            ).all()
            return [
                {
                    "id": f"msg-{r.sequence_no}",
                    "role": r.role,
                    "content": r.content,
                    "sequence_no": r.sequence_no,
                }
                for r in rows
            ]

    async def get_user_id(self, session_id: str) -> int | None:
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            row = (
                await db.execute(
                    select(SessionRow.user_id).where(SessionRow.session_id == session_id)
                )
            ).scalar_one_or_none()
            # select(SessionRow.user_id) 直接返回标量 int，None 表示无记录
            return row

    async def update_title(self, session_id: str, title: str) -> None:
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            await db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(title=title, updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

    async def delete_session(self, session_id: str) -> None:
        # 软删除：标记 deleted_at，保留会话与消息数据。
        self._states.pop(session_id, None)
        async with self._db() as db:
            from app.model.session import Session as SessionRow

            await db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(deleted_at=datetime.now(timezone.utc))
            )
            await db.commit()
