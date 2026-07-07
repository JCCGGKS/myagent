from __future__ import annotations

from app.models import ConversationState
from app.services.routing import StateTrackerService


class ContextService:
    def __init__(
        self,
        state_tracker: StateTrackerService,
        max_recent_messages: int = 6,
        soft_summary_turns: int = 8,
    ) -> None:
        self.state_tracker = state_tracker
        self.max_recent_messages = max_recent_messages
        self.soft_summary_turns = soft_summary_turns

    def compress(self, state: ConversationState) -> ConversationState:
        state.message_history.append({"role": "assistant", "content": state.reply})
        state.recent_messages.append({"role": "assistant", "content": state.reply})

        if len(state.recent_messages) > self.max_recent_messages:
            overflow = state.recent_messages[:-self.max_recent_messages]
            state.recent_messages = state.recent_messages[-self.max_recent_messages :]
            overflow_summary = " ".join(
                f"{item['role']}:{item['content']}" for item in overflow if item.get("content")
            )
            if overflow_summary:
                state.running_summary = " ".join(
                    item for item in [state.running_summary, overflow_summary] if item
                ).strip()

        if len(state.message_history) >= self.soft_summary_turns * 2 and not state.running_summary:
            state.running_summary = self.state_tracker.build_state_summary(state)

        state.summary = self.state_tracker.build_state_summary(state)
        return state
