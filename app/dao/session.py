from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.schema import ConversationState


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class SessionStore(ABC):
    """会话存储接口（dao 层）。业务层只依赖此接口，实现可注入。"""

    @abstractmethod
    def create_session(self, user_id: str, channel: str = "web", title: str = "新会话") -> str:
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
        ...

    @abstractmethod
    def record_handoff(
        self,
        session_id: str,
        handoff_reason: str,
        handoff_summary: str,
        state_snapshot: dict[str, Any],
    ) -> None:
        ...

    @abstractmethod
    def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        ...


class MemorySessionStore(SessionStore):
    """内存实现（本地/测试默认）。与原 app.store.SessionStore 行为一致。"""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def create_session(self, user_id: str, channel: str = "web", title: str = "新会话") -> str:
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
            "state_snapshots": [],
            "tool_calls": [],
            "handoff_records": [],
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
                "state_snapshots": [],
                "tool_calls": [],
                "handoff_records": [],
                "state": None,
            },
        )
        record["state"] = deepcopy(state)
        record["session"].update(
            {
                "user_id": state.user_id,
                "channel": state.channel,
                "status": "handoff" if state.handoff else "active",
                "current_intent": state.current_main_intent,
                "current_stage": state.stage,
                "risk_level": state.risk_level,
                "summary": state.running_summary or state.summary,
                "handoff_required": state.handoff,
                "updated_at": _now(),
            }
        )
        record["state_snapshots"].append(
            {
                "current_intent": state.current_main_intent,
                "sub_intent": state.current_sub_intent,
                "stage": state.stage,
                "slots": deepcopy(state.slots),
                "missing_slots": list(state.missing_slots),
                "confirmed_slots": list(state.confirmed_slots),
                "candidate_intents": list(state.candidate_intents),
                "needs_clarification": state.needs_clarification,
                "topic_changed": state.topic_changed,
                "risk_level": state.risk_level,
                "state_summary": state.summary,
                "running_summary": state.running_summary,
                "current_action": state.current_action,
                "latest_action_result": deepcopy(state.latest_action_result),
                "created_at": _now(),
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
                "state_snapshots": [],
                "tool_calls": [],
                "handoff_records": [],
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
        record = self._sessions.setdefault(
            session_id,
            {
                "session": {"session_id": session_id, "status": "active", "created_at": _now(), "updated_at": _now()},
                "messages": [],
                "state_snapshots": [],
                "tool_calls": [],
                "handoff_records": [],
                "state": None,
            },
        )
        record["tool_calls"].append(
            {
                "tool_name": tool_name,
                "tool_category": tool_category,
                "request_args": deepcopy(request_args),
                "raw_result": deepcopy(raw_result),
                "sanitized_result": deepcopy(sanitized_result),
                "user_facing_summary": user_facing_summary,
                "status": status,
                "created_at": _now(),
            }
        )

    def record_handoff(
        self,
        session_id: str,
        handoff_reason: str,
        handoff_summary: str,
        state_snapshot: dict[str, Any],
    ) -> None:
        record = self._sessions.setdefault(
            session_id,
            {
                "session": {"session_id": session_id, "status": "active", "created_at": _now(), "updated_at": _now()},
                "messages": [],
                "state_snapshots": [],
                "tool_calls": [],
                "handoff_records": [],
                "state": None,
            },
        )
        record["handoff_records"].append(
            {
                "handoff_reason": handoff_reason,
                "handoff_summary": handoff_summary,
                "state_snapshot": deepcopy(state_snapshot),
                "status": "pending",
                "created_at": _now(),
            }
        )

    def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        record = self._sessions.get(session_id)
        return deepcopy(record) if record else None


class SqlSessionStore(SessionStore):
    """MySQL 实现（配置了 mysql 段时注入）。

    保留内存镜像以满足 get() 返回完整 ConversationState 的语义，
    同时把 Session/Message/StateSnapshot/ToolCall/HandoffRecord 落库做审计持久化。
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._states: dict[str, ConversationState] = {}

    def _db(self):
        return self._session_factory()

    def create_session(self, user_id: str, channel: str = "web", title: str = "新会话") -> str:
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
            from app.model.session import (
                Session as SessionRow,
                StateSnapshot,
            )

            row = db.get(SessionRow, state.session_id)
            if row is None:
                row = SessionRow(session_id=state.session_id)
                db.add(row)
            row.user_id = state.user_id
            row.channel = state.channel
            row.status = "handoff" if state.handoff else "active"
            row.current_intent = state.current_main_intent
            row.current_stage = state.stage
            row.risk_level = state.risk_level
            row.summary = state.running_summary or state.summary
            row.handoff_required = state.handoff

            db.add(
                StateSnapshot(
                    session_id=state.session_id,
                    current_intent=state.current_main_intent,
                    sub_intent=state.current_sub_intent,
                    stage=state.stage,
                    slots=state.slots,
                    missing_slots=list(state.missing_slots),
                    confirmed_slots=list(state.confirmed_slots),
                    candidate_intents=list(state.candidate_intents),
                    needs_clarification=state.needs_clarification,
                    topic_changed=state.topic_changed,
                    risk_level=state.risk_level,
                    state_summary=state.summary,
                    running_summary=state.running_summary,
                    current_action=state.current_action,
                    latest_action_result=state.latest_action_result,
                )
            )
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
            from app.model.session import Message

            db.add(
                Message(
                    session_id=session_id,
                    role=role,
                    message_type=message_type,
                    content=content,
                    sanitized_content=sanitized_content or content,
                    sequence_no=0,
                )
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
        with self._db() as db:
            from app.model.session import ToolCall

            db.add(
                ToolCall(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_category=tool_category,
                    request_args=request_args,
                    raw_result=raw_result,
                    sanitized_result=sanitized_result,
                    user_facing_summary=user_facing_summary,
                    status=status,
                )
            )
            db.commit()

    def record_handoff(
        self,
        session_id: str,
        handoff_reason: str,
        handoff_summary: str,
        state_snapshot: dict[str, Any],
    ) -> None:
        with self._db() as db:
            from app.model.session import HandoffRecord

            db.add(
                HandoffRecord(
                    session_id=session_id,
                    handoff_reason=handoff_reason,
                    handoff_summary=handoff_summary,
                    state_snapshot=state_snapshot,
                    status="pending",
                )
            )
            db.commit()

    def dump_session_record(self, session_id: str) -> dict[str, Any] | None:
        state = self._states.get(session_id)
        if state is None:
            return None
        return {"session_id": session_id, "state": deepcopy(state)}
