from __future__ import annotations

import json
import logging
from typing import Any

from app.schema import ConversationState, ToolExecutionResult
from app.business.tools.rag_tool import RagRetrieveTool

logger = logging.getLogger(__name__)


class AgentNodeService:
    """Agent 节点服务（ReAct 循环，工具调用）。"""

    def __init__(
        self,
        llm: Any | None = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tool_rounds: int = 3,
    ) -> None:
        # 兼容旧字段 llm：仍允许直接传入已构造的 client。
        self.llm_client = llm if llm is not None else llm_client
        self.llm_model = llm_model
        self.tools = tools or self._default_tools()
        self.max_tool_rounds = max_tool_rounds

    def run(self, state: ConversationState) -> ConversationState:
        """执行 ReAct 循环，直到 LLM 返回最终响应。"""
        # 1. 构造 messages
        messages = self._build_messages(state)

        # 2. ReAct 循环（最多 max_tool_rounds 轮）
        for round in range(self.max_tool_rounds):
            logger.debug("agent_node: round %d, session=%s", round, state.session_id)

            # 2.1 调用 LLM，传入 tools 参数
            response = self._call_llm(messages)

            # 2.2 如果 LLM 返回 tool_calls，执行工具
            if response.get("tool_calls"):
                for tool_call in response["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    tool_args = json.loads(tool_call["function"]["arguments"])

                    # 执行工具
                    tool_result = self._execute_tool(tool_name, tool_args, state)

                    # 把工具调用和结果追加到 messages
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tool_call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_name,
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )

                # 继续循环，让 LLM 根据工具结果决定下一步
                continue

            # 2.3 如果 LLM 返回最终响应，结束循环
            else:
                state.reply = response.get("content", "")
                break

        # 3. 如果超过最大轮次，强制生成响应（fallback）
        if not state.reply:
            logger.warning("agent_node: max tool rounds reached, session=%s", state.session_id)
            state.reply = self._fallback_response(state)

        # 4. 把工具结果写到 state（供 response_generator 使用）
        state.tool_result = self._collect_tool_results(messages)

        return state

    def _build_messages(self, state: ConversationState) -> list[dict[str, Any]]:
        """从 state 构造 messages（包含历史消息和系统提示）。"""
        messages = []

        # 系统提示
        system_prompt = self._build_system_prompt(state)
        messages.append({"role": "system", "content": system_prompt})

        # 历史消息（最近 10 条）
        recent_messages = state.message_history[-10:]
        messages.extend(recent_messages)

        return messages

    def _build_system_prompt(self, state: ConversationState) -> str:
        """构造系统提示（包含意图、槽位、情绪等上下文）。"""
        prompt = "你是一个客服助手，负责回答用户问题。"
        prompt += f"\n当前意图：{state.current_main_intent}.{state.current_sub_intent}"
        prompt += f"\n当前阶段：{state.stage}"
        if state.slots:
            prompt += f"\n已填槽位：{state.slots}"
        if state.missing_slots:
            prompt += f"\n缺失槽位：{state.missing_slots}"
        prompt += "\n请根据以上信息，选择合适的工具回答问题。如果用户问题不需要工具，直接回答。"
        return prompt

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """调用 LLM，返回响应（包含 content 或 tool_calls）。

        无 client 时降级返回 mock content，避免本地/CI 不接 LLM 时崩溃。
        """
        logger.debug("agent_node: calling LLM with %d messages", len(messages))

        if self.llm_client is None or not self.llm_model:
            return {
                "content": "模拟 LLM 响应（请接入真实 LLM）",
                "tool_calls": [],
            }

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

    def _execute_tool(self, tool_name: str, tool_args: dict, state: ConversationState) -> dict[str, Any]:
        """执行单个工具，返回结构化结果。"""
        logger.info("agent_node: executing tool %s with args %s", tool_name, tool_args)

        if tool_name == "rag_retrieve":
            rag_tool = RagRetrieveTool()
            return {"retrieved_docs": rag_tool.run(tool_args.get("query", ""))}
        elif tool_name == "query_order":
            # TODO: 接入真实订单查询服务
            return {"order_id": tool_args.get("order_id"), "status": "模拟状态"}
        elif tool_name == "query_logistics":
            # TODO: 接入真实物流查询服务
            return {"order_id": tool_args.get("order_id"), "tracking_status": "模拟物流状态"}
        elif tool_name == "create_handoff":
            state.handoff = True
            state.handoff_reason = tool_args.get("reason", "agent_decision")
            return {"ticket_id": "mock_ticket_1", "summary": "模拟转人工"}
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def _collect_tool_results(self, messages: list[dict[str, Any]]) -> ToolExecutionResult | None:
        """从 messages 中收集工具结果，写到 state.tool_result。"""
        # 找到最后一条 tool 消息
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                tool_name = msg.get("name", "")
                content = json.loads(msg.get("content", "{}"))
                return ToolExecutionResult(
                    kind=tool_name,
                    raw_result=content,
                    sanitized_result=content,
                    user_facing_summary=str(content)[:200],
                )
        return None

    def _fallback_response(self, state: ConversationState) -> str:
        """当超过最大工具轮次时，生成 fallback 响应。"""
        return "抱歉，我需要更多时间来回答你的问题。请稍后再试，或联系人工客服。"

    def _default_tools(self) -> list[dict[str, Any]]:
        """默认工具列表（rag_retrieve, query_order, query_logistics, create_handoff）。"""
        rag_tool = RagRetrieveTool()
        return [rag_tool.to_tool_schema()]
