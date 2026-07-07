from __future__ import annotations

from app.models import ConversationState, ToolExecutionResult
from app.rag.knowledge_base import KnowledgeBaseService
from app.utils import build_action_record


class RagRetrievalService:
    def __init__(self, knowledge_base: KnowledgeBaseService) -> None:
        self.knowledge_base = knowledge_base

    def retrieve(self, state: ConversationState) -> ConversationState:
        hits = self.knowledge_base.search(state.last_user_message)
        state.retrieved_knowledge = hits
        summary = hits[0].answer if hits else "未命中知识库答案"
        state.tool_result = ToolExecutionResult(
            kind="knowledge",
            raw_result={"hits": [hit.model_dump() for hit in hits]},
            sanitized_result=hits[0].model_dump() if hits else None,
            user_facing_summary=summary,
        )
        state.latest_action_name = "knowledge_retriever"
        state.latest_action_result = state.tool_result.sanitized_result
        state.action_history.append(build_action_record("knowledge_retriever", summary))
        return state
