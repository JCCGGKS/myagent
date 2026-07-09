from __future__ import annotations

from datetime import UTC, datetime

from app.schema import ActionRecord


def build_action_record(action_name: str, summary: str) -> ActionRecord:
    return ActionRecord(
        action_name=action_name,
        summary=summary,
        created_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
