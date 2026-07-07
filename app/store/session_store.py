from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.models import ConversationState


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def get(self, session_id: str) -> ConversationState | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        return deepcopy(record["state"])

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
                "state": deepcopy(state),
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
