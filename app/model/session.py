from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model import Base


class Session(Base):
    """会话元信息。"""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="web")
    status: Mapped[str] = mapped_column(String(32), default="active")
    current_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    handoff_required: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Message(Base):
    """会话消息流。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.session_id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StateSnapshot(Base):
    """会话状态快照。"""

    __tablename__ = "state_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.session_id"), index=True, nullable=False
    )
    current_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sub_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slots: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_slots: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_slots: Mapped[list] = mapped_column(JSON, default=list)
    candidate_intents: Mapped[list] = mapped_column(JSON, default=list)
    needs_clarification: Mapped[bool] = mapped_column(default=False)
    topic_changed: Mapped[bool] = mapped_column(default=False)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    state_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    running_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_action_result: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ToolCall(Base):
    """工具调用审计。"""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.session_id"), index=True, nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_category: Mapped[str] = mapped_column(String(32), default="query")
    request_args: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_result: Mapped[dict] = mapped_column(JSON, nullable=True)
    sanitized_result: Mapped[dict] = mapped_column(JSON, nullable=True)
    user_facing_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HandoffRecord(Base):
    """转人工记录。"""

    __tablename__ = "handoff_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.session_id"), index=True, nullable=False
    )
    handoff_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handoff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_snapshot: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
