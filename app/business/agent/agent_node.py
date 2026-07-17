from __future__ import annotations

from typing import Any

from app.config import LLMConfig
from app.schema import ConversationState
from app.business.prompts import build_agent_system_prompt
from app.business.tools.tool_executor import ToolExecutor
from app.business.tools.registry import build_tool_schemas
from app.utils.llm import call_llm_async
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("agent")


class AgentNodeService:
    """Agent 节点服务（ReAct 循环，决策与工具编排）。

    本节点只做**决策与工具编排**：判断调哪个工具、把工具结果（``state.tool_results``，
    结构化数据列表）与状态标志写回，由下游 ``response_generator`` 基于 ``state.tool_results``
    + ``response_prompts.yml`` 模板统一生成面向用户的回复。工具结果产生的回复**绝不**在本
    节点产出（避免硬编码话术外泄，且保证文案单一来源）。

    仅当 LLM 直接给出结论、整轮从未调用工具时，才把 ``content`` 写入 ``state.reply``
    作为直答（下游 generator 命中早返回、不再多调一次 LLM，去冗余）。
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
        """执行 ReAct 循环（异步）：调 LLM → 无 tool_calls 则直答；有 tool_calls 则执行后继续。

        关键修复：只有当**整轮循环从未调用过工具**时，才把 LLM 的收尾文本当作最终
        回复写入 ``state.reply``（这是「LLM 直接作答、无需工具」的情形，下游
        ``response_generator`` 命中早返回、避免重复调 LLM 重新措辞）。

        一旦调用过工具，收尾轮的 ``content`` 往往只是模型的「已有足够信息、无需再调
        工具」之类的**决策旁白**，并非面向用户的答案。此时**不**写入 ``state.reply``，
        且工具 handler 也只回填 ``state.tool_results``（结构化列表），绝不写回复文案——
        留空交由 ``response_generator`` 基于 ``tool_results`` + yml 模板生成友好回答
        （其本职就是根据工具结果措辞）。否则用户会收到模型内部决策文本（见评估发现）。
        """
        messages = self._build_messages(state)
        tool_called = False
        logger.info(_tagged("agent", "run start session=%s main=%s"), state.session_id, state.current_main_intent)

        for _round in range(self.max_tool_rounds):
            logger.debug(_tagged("agent", "run round=%d session=%s"), _round, state.session_id)

            # 每轮刷新系统提示中的「已执行工具」清单（基于本轮前的 tool_cache），
            # 让模型看到本 turn 已查过哪些工具与参数，从源头避免重复调用。
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = build_agent_system_prompt(state)

            response = await self._call_llm(messages)

            if response.get("tool_calls"):
                tool_called = True
                for tool_call in response["tool_calls"]:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [tool_call],
                        }
                    )
                cache_before = len(state.tool_cache or {})
                tool_messages = await self.tool_executor.run(response["tool_calls"], state)
                messages.extend(tool_messages)
                # 终态硬中断：本轮工具结果含 handoff / confirmation → 本 turn 动作已闭环
                # （转人工单已建 / R1 挂起待用户确认），无需再调下一轮 LLM，直接结束循环
                # 交由 response_generator 生成。信号源是代码产出的 ToolExecutionResult.kind，
                # 确定可靠，不依赖 LLM 自觉停止（避免其收尾判断失误导致的冗余轮次）。
                if any(
                    getattr(r, "kind", None) in ("handoff", "confirmation")
                    for r in state.tool_results
                ):
                    logger.info(
                        _tagged("agent", "terminal tool result (handoff/confirmation), break loop session=%s"),
                        state.session_id,
                    )
                    break
                # ReAct stopping guard（治本，不依赖模型自觉停）：本轮 LLM 提出的工具调用
                # 全部已被本 turn 执行过——tool_cache 本轮未新增任何键（即全是执行层缓存命中
                # 或批次内去重），说明模型在前几轮已取得全部所需信息、却未发出收尾信号。
                # 此时再调 LLM 只会空转重发相同工具，直接结束循环，交由 response_generator
                # 基于已有 tool_results 生成回复。net-new 判定天然兼容 R1 二次确认：
                # request_refund(confirm=false) 与 (confirm=true) 是不同参数 → 不同缓存键
                # → 视为新调用、继续循环，不被误停。
                if len(state.tool_cache or {}) == cache_before:
                    logger.info(
                        _tagged("agent", "no net-new tool execution this round (all cached), stop loop session=%s"),
                        state.session_id,
                    )
                    break
                # 否则本轮确有新增工具执行，继续循环让 LLM 根据结果决定下一步
                continue

            # 无 tool_calls：调度节点只做决策/工具调用，其 content 输出是内部决策旁白，
            # 绝不能当作面向用户的回复（否则会把「直接结束本节点、由回复节点…」这类
            # 内部 monologue 漏给用户）。用户回复统一交给 response_generator 基于
            # 上下文生成——即便本轮确实无需工具，也由下游产出干净话术，而非调度节点的自言自语。
            content = (response.get("content") or "").strip()
            if content and not tool_called:
                logger.debug(_tagged("agent", "scheduler emitted non-tool text, discarding as user reply: %r"), content[:80])
            break

        # 若超过最大轮次仍只有 tool_calls，response_generator 会基于已有 tool_results 兜底生成
        logger.info(_tagged("agent", "run end session=%s tool_called=%s"), state.session_id, tool_called)
        return state

    def _build_messages(self, state: ConversationState) -> list[dict[str, Any]]:
        """从 state 构造 messages（包含历史消息和系统提示）。

        上下文来自摘要缓冲：running_summary（窗口外已压缩内容）+ recent_messages
        （活动窗口内的近期消息）。
        """
        messages = []

        # 系统提示（工具信息仍经 tools= API 参数下发，提示词不重复罗列）
        system_prompt = build_agent_system_prompt(state)
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
        logger.debug(_tagged("agent", "calling LLM with %d messages"), len(messages))
        return await call_llm_async(
            self.llm_client,
            self.llm_model,
            messages,
            tools=self.tools,
            generation_kwargs=self.generation_kwargs,
        )
