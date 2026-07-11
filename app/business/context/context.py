from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Union

from app.schema import ConversationState
from app.business.context.state_summary import build_state_summary

# 摘要折叠器：同步 (old_summary, overflow) -> str，或异步 -> Awaitable[str]
Summarizer = Callable[[str, list[dict]], Union[str, Awaitable[str]]]


class ContextService:
    def __init__(
        self,
        state_tracker: object | None = None,
        max_recent_messages: int = 6,
        summarizer: Summarizer | None = None,
        max_summary_chars: int = 2000,
    ) -> None:
        self.state_tracker = state_tracker
        # 活动窗口上限：窗口内的消息原样保留，窗口外折叠进 running_summary
        self.max_recent_messages = max_recent_messages
        # 可选 LLM 折叠器：签名为 (old_summary: str, overflow: list[dict]) -> str
        # 不传则退化为文本拼接 + 长度截断
        self.summarizer = summarizer
        # 退化模式下 running_summary 的最大长度，避免无限增长
        self.max_summary_chars = max_summary_chars

    async def compress(self, state: ConversationState) -> ConversationState:
        # 本轮助手回复写入活动窗口
        state.recent_messages.append({"role": "assistant", "content": state.reply})

        # 活动窗口溢出 -> 折叠进 running_summary（摘要缓冲）
        if len(state.recent_messages) > self.max_recent_messages:
            overflow = state.recent_messages[: -self.max_recent_messages]
            state.recent_messages = state.recent_messages[-self.max_recent_messages :]
            state.running_summary = await self._fold_summary(state.running_summary, overflow)

        # summary 为每轮一句话状态快照（与叙述性 running_summary 职责区分）
        state.summary = build_state_summary(state)
        return state

    async def _fold_summary(self, old_summary: str, overflow: list[dict]) -> str:
        """把溢出消息折叠进既有摘要（异步）。

        - 有 summarizer：交给 LLM 折叠（保持有界、连贯），支持同步或异步折叠器。
        - 无 summarizer：退化为 "role:content" 拼接，并截断到 max_summary_chars。
        """
        if self.summarizer is not None:
            try:
                folded = self.summarizer(old_summary, overflow)
                if hasattr(folded, "__await__"):
                    folded = await folded
                if folded:
                    return folded
            except Exception:
                # 折叠失败不影响主流程，降级为拼接
                pass
        folded = " ".join(
            f"{item['role']}:{item.get('content', '')}"
            for item in overflow
            if item.get("content")
        )
        merged = " ".join(p for p in [old_summary, folded] if p).strip()
        if len(merged) > self.max_summary_chars:
            merged = merged[-self.max_summary_chars :]
        return merged
