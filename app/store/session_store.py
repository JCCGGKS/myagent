from __future__ import annotations

from copy import deepcopy

from app.models import ConversationState


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}

    def get(self, session_id: str) -> ConversationState | None:
        state = self._sessions.get(session_id)
        return deepcopy(state) if state else None

    def save(self, state: ConversationState) -> ConversationState:
        self._sessions[state.session_id] = deepcopy(state)
        return state
