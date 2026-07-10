from __future__ import annotations

import json
import logging
from typing import Any

from app.schema import ConversationState
from app.business.prompts import build_agent_system_prompt
from app.business.tools.rag_tool import RagRetrieveTool
from app.business.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class AgentNodeService:
    """Agent 节点服务（ReAct 循环，仅负责决策与工具编排）。

    最终答案由 response_generator 节点统一生成；本节点不写 ``state.reply``。
    """

    def __init__(
        self,
        llm: Any | None = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        max_tool_rounds: int = 3,
    ) -> None:
        # 兼容旧字段 llm：仍允许直接传入已构造的 client。
        self.llm_client = llm if llm is not None else llm_client
        self.llm_model = llm_model
        self.tools = tools or self._default_tools()
        self.tool_executor = tool_executor or ToolExecutor()
        self.max_tool_rounds = max_tool_rounds

    def run(self, state: ConversationState) -> ConversationState:
        """执行 ReAct 循环：调 LLM → 无 tool_calls 则交给 generator；有 tool_calls 则执行后继续。"""
        messages = self._build_messages(state)

        for _round in range(self.max_tool_rounds):
            logger.debug("agent_node: round %d, session=%s", _round, state.session_id)

            response = self._call_llm(messages)

            if response.get("tool_calls"):
                for tool_call in response["tool_calls"]:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [tool_call],
                        }
                    )
                tool_messages = self.tool_executor.run(response["tool_calls"], state)
                messages.extend(tool_messages)
                # 继续循环，让 LLM 根据工具结果决定下一步
                continue

            # 无 tool_calls：信息已足够，交给 response_generator 生成最终答案
            break

        # 若超过最大轮次仍只有 tool_calls，response_generator 会基于已有 tool_result 兜底生成
        return state

    def _build_messages(self, state: ConversationState) -> list[dict[str, Any]]:
        """从 state 构造 messages（包含历史消息和系统提示）。"""
        messages = []

        # 系统提示
        system_prompt = build_agent_system_prompt(state)
        messages.append({"role": "system", "content": system_prompt})

        # 历史消息（最近 10 条）
        recent_messages = state.message_history[-10:]
        messages.extend(recent_messages)

        return messages

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """调用 LLM，返回响应（包含 content 或 tool_calls）。"""
        logger.debug("agent_node: calling LLM with %d messages", len(messages))
        if self.llm_client is None or not self.llm_model:
            raise RuntimeError(
                "LLM client is not configured; a real LLM client is required "
                "to run the agent node."
            )

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                tools=self.tools if self.tools else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_node: LLM call failed err=%r", exc)
            return {"content": "抱歉，我暂时无法回答这个问题。", "tool_calls": []}

        if not response.choices:
            return {"content": "", "tool_calls": []}

        message = response.choices[0].message
        content = message.content or ""
        tool_calls: list[dict[str, Any]] = []
        for tc in getattr(message, "tool_calls", None) or []:
            tool_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
            )
        return {"content": content, "tool_calls": tool_calls}

    def _default_tools(self) -> list[dict[str, Any]]:
        """默认工具列表（rag_retrieve, query_order, query_logistics, create_handoff）。"""
        rag_tool = RagRetrieveTool()
        return [rag_tool.to_tool_schema()]
