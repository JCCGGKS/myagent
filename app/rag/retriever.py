from __future__ import annotations

from app.models import ConversationState, ToolExecutionResult
from app.utils import build_action_record


class RagRetrievalService:
    def retrieve(self, state: ConversationState) -> ConversationState:
        """知识检索节点（当前无内置知识库，直接返回空结果）。"""
        state.tool_result = ToolExecutionResult(
            kind="knowledge",
            raw_result={"hits": []},
            sanitized_result=None,
            user_facing_summary="",
        )
        state.latest_action_name = "knowledge_retriever"
        state.latest_action_result = None
        state.action_history.append(build_action_record("knowledge_retriever", ""))
        return state
