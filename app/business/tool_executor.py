from __future__ import annotations

import json
import logging
from typing import Any

from app.schema import ConversationState, ToolExecutionResult
from app.business.execution import ExecutionService
from app.business.tools.rag_tool import RagRetrieveTool

logger = logging.getLogger(__name__)


class ToolExecutor:
    """统一的工具执行服务：覆盖 LLM 函数调用工具与业务工具。

    agent_node 调用 ``run`` 执行一批 tool_calls，返回 tool 结果消息
    （追加到 ReAct 线程），并把最后一次结果写入 ``state.tool_result``。
    """

    def __init__(
        self,
        execution_service: ExecutionService | None = None,
        rag_tool: RagRetrieveTool | None = None,
    ) -> None:
        self.execution_service = execution_service
        self.rag_tool = rag_tool or RagRetrieveTool()

    def run(
        self, tool_calls: list[dict[str, Any]], state: ConversationState
    ) -> list[dict[str, Any]]:
        tool_messages: list[dict[str, Any]] = []
        last_result: ToolExecutionResult | None = None
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            result = self._execute_one(name, args, state)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": name,
                    "content": json.dumps(
                        result.model_dump() if isinstance(result, ToolExecutionResult) else result,
                        ensure_ascii=False,
                    ),
                }
            )
            if isinstance(result, ToolExecutionResult):
                last_result = result
        if last_result is not None:
            state.tool_result = last_result
        return tool_messages

    def _execute_one(
        self, name: str, args: dict[str, Any], state: ConversationState
    ) -> ToolExecutionResult | dict[str, Any]:
        logger.info("ToolExecutor: executing %s args=%s", name, args)
        if name == "rag_retrieve":
            docs = self.rag_tool.run(args.get("query", ""), user_id=state.user_id)
            return ToolExecutionResult(
                kind="knowledge",
                raw_result={"retrieved_docs": docs},
                sanitized_result={"retrieved_docs": docs},
                user_facing_summary=f"检索到 {len(docs)} 条相关文档",
            )
        if self.execution_service is not None:
            return self.execution_service.run_tool(name, args, state)
        return ToolExecutionResult(
            kind="error",
            user_facing_summary=f"工具执行服务未配置，无法执行: {name}",
        )
