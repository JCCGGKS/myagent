from __future__ import annotations

from app.schema import ConversationState

SYSTEM_PROMPT_PREFIX = "你是一个客服助手，负责回答用户问题。"

# 仅向 LLM 透传对「执行」有帮助的字段。
# 状态对象承载了大量仅供执行/调度使用的字段（会话标识、渠道、内部计数、
# 历史归档、工具结果等），它们对 LLM 生成回复或决策没有帮助，直接透传只
# 会增加 token 成本与噪声。这里用白名单显式界定「提示词可见」的上下文切片，
# 实现状态对象到提示词的上下文隔离：白名单之外的字段一律不进入提示词。
_PROMPT_CONTEXT_FIELDS = (
    "current_main_intent",
    "current_sub_intent",
    "stage",
    "slots",
    "missing_slots",
    "confirmed_slots",
    "emotion",
    "needs_clarification",
)


def build_prompt_context(state: ConversationState) -> dict:
    """从状态对象抽取「提示词可见」的上下文切片（上下文隔离）。

    只保留与「当前意图 + 槽位 + 情绪」相关的字段，其余字段（如
    ``session_id`` / ``user_id`` / ``channel`` / ``action_history`` /
    ``running_summary`` / ``recent_messages`` / ``pending_intents`` / 各类
    计数器 / ``reply`` 等执行侧上下文）一律不进入提示词。省略空值字段以
    保持提示词紧凑。
    """
    ctx: dict = {}
    for field in _PROMPT_CONTEXT_FIELDS:
        value = getattr(state, field)
        if value in (None, "", {}, []):
            continue
        ctx[field] = value
    return ctx


def _render_base_context(ctx: dict) -> str:
    """把隔离后的上下文切片渲染成提示词公共片段。"""
    prompt = SYSTEM_PROMPT_PREFIX
    if "current_main_intent" in ctx:
        prompt += f"\n当前意图：{ctx['current_main_intent']}.{ctx.get('current_sub_intent', '')}"
    if "stage" in ctx:
        prompt += f"\n当前阶段：{ctx['stage']}"
    if "slots" in ctx:
        prompt += f"\n已填槽位：{ctx['slots']}"
    if "missing_slots" in ctx:
        prompt += f"\n缺失槽位：{ctx['missing_slots']}"
    if "confirmed_slots" in ctx:
        prompt += f"\n已确认槽位：{ctx['confirmed_slots']}"
    if "emotion" in ctx:
        prompt += f"\n用户情绪：{ctx['emotion'].primary}"
    if ctx.get("needs_clarification"):
        prompt += "\n需要澄清：是"
    return prompt


def _build_base_system_prompt(state: ConversationState) -> str:
    """构造系统提示的公共部分（意图、阶段、槽位等上下文）。"""
    return _render_base_context(build_prompt_context(state))


def _render_tools(tools: list[dict] | None) -> str:
    """把工具 schema 渲染成「名称：描述」清单（供提示词告知模型可调用的工具）。

    只取 function.name / function.description，不重复整段 JSON schema——
    结构化 schema 已由 ``tools=`` API 参数下发给模型用于 function calling，
    此处仅以自然语言补充一份「可调用工具目录」，让模型知道有哪些工具可用。
    """
    if not tools:
        return ""
    lines = []
    for tool in tools:
        func = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = func.get("name")
        desc = func.get("description", "")
        if name:
            lines.append(f"- {name}：{desc}")
    return "\n".join(lines)


def build_agent_system_prompt(
    state: ConversationState, tools: list[dict] | None = None
) -> str:
    """Agent 节点系统提示（仅工具编排/决策，不生成最终答案）。

    明确告知 LLM：本节点负责判断是否调用工具获取信息；
    当已有足够信息（无需再调用工具）时，结束本节点、由回复节点生成最终答案。
    通过 ``tools=`` API 参数下发的工具 schema 已具备 function calling 能力，
    这里额外以自然语言列出可调用工具目录，让模型清楚有哪些工具可用。
    """
    prompt = _build_base_system_prompt(state)
    prompt += (
        "\n\n你是客服助手的【调度节点】，只负责决定下一步动作："
        "\n1. 若需要更多信息来回答用户（如订单状态、物流、知识库内容），请调用合适的工具；"
        "\n2. 若当前上下文已足够回答用户，请不要调用任何工具，直接结束本节点。"
        "\n注意：你只做决策与工具调用，不要在此输出给用户的最终回复，最终回复由专门的回复节点生成。"
    )
    tools_text = _render_tools(tools)
    if tools_text:
        prompt += "\n\n当前可调用的工具：\n" + tools_text
    return prompt


def _append_examples(prompt: str, examples: str | None) -> str:
    """将示例参考拼接为提示词的固定小节。"""
    if examples:
        prompt += "\n\n【回复示例参考】\n" + examples
    return prompt


def build_clarification_system_prompt(
    state: ConversationState, examples: str | None = None
) -> str:
    """澄清节点系统提示（生成追问话术，需补全信息时调用）。"""
    prompt = _build_base_system_prompt(state)
    # current_action 仅澄清节点需要，作为节点专属上下文追加（基于已隔离的状态切片）。
    if state.current_action:
        prompt += f"\n当前动作：{state.current_action}"
    prompt += (
        "\n\n你是客服助手，当前需要向用户追问以补全信息。"
        f"\n缺失槽位：{state.missing_slots}"
        "\n请生成一句友好的追问话术，引导用户补充所需信息（例如缺订单号时请用户提供订单号）。"
        "只输出追问内容本身，不要包含多余解释或客套话。"
    )
    return _append_examples(prompt, examples)


def build_response_system_prompt(
    state: ConversationState, examples: str | None = None
) -> str:
    """回复生成节点的系统提示（含工具结果，要求生成友好响应）。"""
    prompt = _build_base_system_prompt(state)
    # tool_result 是执行产物、供回复引用，仅在回复节点显式透传（其余节点不透传）。
    if state.tool_result:
        prompt += f"\n工具调用结果：{state.tool_result.model_dump()}"
    prompt += "\n请根据以上信息，生成友好的客服响应，语气与下方示例保持一致。"
    return _append_examples(prompt, examples)
