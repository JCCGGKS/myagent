from __future__ import annotations

import logging
from typing import Any

from app.config import LLMConfig
from app.schema import ConversationState
from app.business.prompts import build_agent_system_prompt
from app.business.tools.tool_executor import ToolExecutor
from app.business.tools.registry import build_tool_schemas
from app.utils.llm import call_llm_async

logger = logging.getLogger(__name__)


class AgentNodeService:
    """Agent 节点服务（ReAct 循环，决策与工具编排）。

    当 LLM 直接给出结论（无 tool_calls）时，本节点把 ``content`` 写入
    ``state.reply``，使下游 ``response_generator`` 命中早返回、不再多调一次 LLM
    （去冗余，详见任务「去冗余调用」）。需要工具或超限兜底时仍交给 generator。
    """

    def __init__(
        self,
        llm: Any | None = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        max_tool_rounds: int = 3,
        llm_config: LLMConfig | None = None,
    ) -> None:
        # 兼容旧字段 llm：仍允许直接传入已构造的 client。
        self.llm_client = llm if llm is not None else llm_client
        self.llm_model = llm_model
        self.tools = tools or build_tool_schemas()
        self.tool_executor = tool_executor or ToolExecutor()
        self.max_tool_rounds = max_tool_rounds
        # 生成参数（thinking/temperature 等）由 LLMConfig 统一下发，默认关闭思维链。
        self.generation_kwargs = llm_config.generation_kwargs() if llm_config is not None else {}

    async def run(self, state: ConversationState) -> ConversationState:
        """执行 ReAct 循环（异步）：调 LLM → 无 tool_calls 则直接写 reply；有 tool_calls 则执行后继续。"""
        messages = self._build_messages(state)

        for _round in range(self.max_tool_rounds):
            logger.debug("agent_node: round %d, session=%s", _round, state.session_id)

            response = await self._call_llm(messages)

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

            # 无 tool_calls：LLM 已给出结论，直接写入 reply 供 response_generator
            # 早返回（去冗余，避免再调一次 LLM 重新措辞）。
            content = (response.get("content") or "").strip()
            if content:
                state.reply = content
            break

        # 若超过最大轮次仍只有 tool_calls，response_generator 会基于已有 tool_result 兜底生成
        return state

    def _build_messages(self, state: ConversationState) -> list[dict[str, Any]]:
        """从 state 构造 messages（包含历史消息和系统提示）。

        上下文来自摘要缓冲：running_summary（窗口外已压缩内容）+ recent_messages
        （活动窗口内的近期消息）。
        """
        messages = []

        # 系统提示（附带可调用工具目录，供模型决策调用）
        system_prompt = build_agent_system_prompt(state, tools=self.tools)
        messages.append({"role": "system", "content": system_prompt})

        # 注入压缩摘要缓冲：让模型看到活动窗口之外的上下文
        if state.running_summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是此前的对话摘要（已压缩）：\n{state.running_summary}",
                }
            )

        # 仅发送活动窗口内的近期消息
        messages.extend(state.recent_messages)

        return messages

    async def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """调用 LLM（异步），返回响应（包含 content 或 tool_calls）。"""
        logger.debug("agent_node: calling LLM with %d messages", len(messages))
        return await call_llm_async(
            self.llm_client,
            self.llm_model,
            messages,
            tools=self.tools,
            generation_kwargs=self.generation_kwargs,
        )
