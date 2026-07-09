from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, update

from app.schema import ConversationState
from app.utils import log_tool_call


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class SessionStore(ABC):
    """会话存储接口（dao 层）。业务层只依赖此接口，实现可注入。"""

    @abstractmethod
    def create_session(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        ...

    @abstractmethod
    def get(self, session_id: str) -> ConversationState | None:
        ...

    @abstractmethod
    def save(self, state: ConversationState) -> ConversationState:
        ...

    @abstractmethod
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        ...

    @abstractmethod
    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        tool_category: str,
        request_args: dict[str, Any],
        raw_result: dict[str, Any] | None,
        sanitized_result: dict[str, Any] | None,
        user_facing_summary: str,
        status: str = "success",
    ) -> None:
        """记录一次工具调用（MVP 通道下为 no-op，保留接口以备后续接入 tool_calls 表）。"""

    @abstractmethod
    def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        """列出某用户的会话（含 title / updated_at / preview），按 updated_at 倒序。"""

    @abstractmethod
    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """读取某会话的历史消息（role / content），按 sequence_no 正序。"""

    @abstractmethod
    def get_user_id(self, session_id: str) -> int | None:
        """获取某会话的归属 user_id，不存在返回 None。"""

    @abstractmethod
    def update_title(self, session_id: str, title: str) -> None:
        """更新会话名称。"""

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """软删除会话（标记 deleted_at，保留数据与消息）。"""


class MemorySessionStore(SessionStore):
    """内存实现（本地/测试默认）。与原 app.store.SessionStore 行为一致。"""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def create_session(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = {
            "session": {
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
                "title": title,
                "status": "active",
                "created_at": _now(),
                "updated_at": _now(),
            },
            "messages": [],
            "state": None,
        }
        return session_id

    def get(self, session_id: str) -> ConversationState | None:
        record = self._sessions.get(session_id)
        return deepcopy(record["state"]) if record else None

    def save(self, state: ConversationState) -> ConversationState:
        record = self._sessions.setdefault(
            state.session_id,
            {
                "session": {
                    "session_id": state.session_id,
                    "user_id": state.user_id,
                    "channel": state.channel,
                    "status": "active",
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
                "status": "handoff" if state.handoff else "active",
                "summary": state.running_summary or state.summary,
                "updated_at": _now(),
            }
        )
        return state

    def append_message(
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
                    "status": "active",
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

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        tool_category: str,
        request_args: dict[str, Any],
        raw_result: dict[str, Any] | None,
        sanitized_result: dict[str, Any] | None,
        user_facing_summary: str,
        status: str = "success",
    ) -> None:
        # tool_calls 表已从本通道移除；改为写入独立 tool.log，便于调试与评测采样。
        log_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            tool_category=tool_category,
            request_args=request_args,
            sanitized_result=sanitized_result,
            user_facing_summary=user_facing_summary,
            status=status,
        )

    def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        record = self._sessions.get(session_id)
        return deepcopy(record) if record else None

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in self._sessions.values():
            session = record.get("session", {})
            if session.get("user_id") != user_id:
                continue
            if session.get("deleted_at") is not None:
                continue
            messages = record.get("messages", [])
            preview = messages[-1]["content"] if messages else ""
            result.append(
                {
                    "session_id": session.get("session_id"),
                    "title": session.get("title", "新会话"),
                    "updated_at": session.get("updated_at"),
                    "preview": preview,
                }
            )
        result.sort(key=lambda s: str(s.get("updated_at") or ""), reverse=True)
        return result

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        record = self._sessions.get(session_id)
        if record is None:
            return []
        messages = record.get("messages", [])
        return [
            {"role": m["role"], "content": m["content"], "sequence_no": m["sequence_no"]}
            for m in sorted(messages, key=lambda m: m.get("sequence_no", 0))
        ]

    def get_user_id(self, session_id: str) -> int | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        return record.get("session", {}).get("user_id")

    def update_title(self, session_id: str, title: str) -> None:
        record = self._sessions.get(session_id)
        if record is not None:
            record.setdefault("session", {})["title"] = title
            record["session"]["updated_at"] = _now()

    def delete_session(self, session_id: str) -> None:
        record = self._sessions.get(session_id)
        if record is not None:
            record.setdefault("session", {})["deleted_at"] = _now()


class SqlSessionStore(SessionStore):
    """MySQL 实现（配置了 mysql 段时注入）。

    保留内存镜像以满足 get() 返回完整 ConversationState 的语义，
    同时把 sessions / messages 落库做会话持久化。
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._states: dict[str, ConversationState] = {}

    def _db(self):
        return self._session_factory()

    def create_session(self, user_id: int, channel: str = "web", title: str = "新会话") -> str:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self._states[session_id] = None
        with self._db() as db:
            from app.model.session import Session as SessionRow

            db.add(
                SessionRow(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    title=title,
                    status="active",
                )
            )
            db.commit()
        return session_id

    def get(self, session_id: str) -> ConversationState | None:
        state = self._states.get(session_id)
        return deepcopy(state) if state else None

    def save(self, state: ConversationState) -> ConversationState:
        self._states[state.session_id] = deepcopy(state)
        with self._db() as db:
            from app.model.session import Session as SessionRow

            row = (
                db.query(SessionRow)
                .filter(SessionRow.session_id == state.session_id)
                .one_or_none()
            )
            if row is None:
                row = SessionRow(session_id=state.session_id)
                db.add(row)
            row.user_id = state.user_id
            row.channel = state.channel
            row.status = "handoff" if state.handoff else "active"
            row.summary = state.running_summary or state.summary
            db.commit()
        return state

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        sanitized_content: str | None = None,
    ) -> None:
        with self._db() as db:
            from app.model.session import Message, Session as SessionRow

            max_seq = db.query(func.coalesce(func.max(Message.sequence_no), 0)).filter(
                Message.session_id == session_id
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
            db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(updated_at=datetime.now(UTC))
            )
            db.commit()

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        tool_category: str,
        request_args: dict[str, Any],
        raw_result: dict[str, Any] | None,
        sanitized_result: dict[str, Any] | None,
        user_facing_summary: str,
        status: str = "success",
    ) -> None:
        # tool_calls 表已从本通道移除；改为写入独立 tool.log，便于调试与评测采样。
        log_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            tool_category=tool_category,
            request_args=request_args,
            sanitized_result=sanitized_result,
            user_facing_summary=user_facing_summary,
            status=status,
        )

    def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        state = self._states.get(session_id)
        if state is None:
            return None
        return {"session_id": session_id, "state": deepcopy(state)}

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        with self._db() as db:
            from app.model.session import Message, Session as SessionRow

            latest = (
                db.query(Message.content)
                .filter(Message.session_id == SessionRow.session_id)
                .order_by(Message.created_at.desc())
                .limit(1)
                .correlate(SessionRow)
                .scalar_subquery()
            )
            rows = (
                db.query(
                    SessionRow.session_id,
                    SessionRow.title,
                    SessionRow.updated_at,
                    latest.label("preview"),
                )
                .filter(SessionRow.user_id == user_id)
                .filter(SessionRow.deleted_at.is_(None))
                .order_by(SessionRow.updated_at.desc())
                .all()
            )
            return [
                {
                    "session_id": r.session_id,
                    "title": r.title,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "preview": r.preview or "",
                }
                for r in rows
            ]

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            from app.model.session import Message

            rows = (
                db.query(Message.role, Message.content, Message.sequence_no)
                .filter(Message.session_id == session_id)
                .order_by(Message.created_at.asc())
                .all()
            )
            return [
                {"role": r.role, "content": r.content, "sequence_no": r.sequence_no}
                for r in rows
            ]

    def get_user_id(self, session_id: str) -> int | None:
        with self._db() as db:
            from app.model.session import Session as SessionRow

            row = (
                db.query(SessionRow.user_id)
                .filter(SessionRow.session_id == session_id)
                .one_or_none()
            )
            return row.user_id if row is not None else None

    def update_title(self, session_id: str, title: str) -> None:
        with self._db() as db:
            from app.model.session import Session as SessionRow

            db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(title=title, updated_at=datetime.now(UTC))
            )
            db.commit()

    def delete_session(self, session_id: str) -> None:
        # 软删除：标记 deleted_at，保留会话与消息数据。
        self._states.pop(session_id, None)
        with self._db() as db:
            from app.model.session import Session as SessionRow

            db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(deleted_at=datetime.now(UTC))
            )
            db.commit()
