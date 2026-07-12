from __future__ import annotations

from app.schema import ConversationState


def build_state_summary(state: ConversationState) -> str:
    """根据会话状态生成一句话摘要（供 context 压缩与状态追踪共用）。"""
    parts = [
        f"用户当前主意图={state.current_main_intent}",
        f"子意图={state.current_sub_intent}",
    ]
    if state.slots:
        parts.append(f"已确认槽位={state.slots}")
    if state.missing_slots:
        parts.append(f"仍缺槽位={state.missing_slots}")
    if state.action_history:
        parts.append(f"最近动作结果={state.action_history[-1].summary}")
    return "；".join(parts)
