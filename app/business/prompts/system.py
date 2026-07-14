from __future__ import annotations

from typing import Any

from app.schema import ConversationState

SYSTEM_PROMPT_PREFIX = "你是一个客服助手，负责回答用户问题。"

# 视为「空」、不进入提示词的字段取值。
_EMPTY_VALUES = (None, "", {}, [])

# 每个节点只取「对它本身执行有帮助」的状态字段——通过不同的字段
# 白名单做上下文隔离，避免把无关字段喂给对应助手。例如：
# - 调度节点（agent）只需意图/阶段/槽位/当前动作来决策调工具，不需要情绪；
# - 澄清节点需要缺失槽位/当前动作来生成追问，并借情绪定语气；
# - 最终回复节点需要已确认槽位/情绪/是否需要澄清来组织友好回复。
# 白名单之外的字段（session_id / user_id / channel / action_history /
# running_summary / recent_messages / pending_intents / 计数器 / reply 等）
# 一律不进入提示词，也不被任何节点透传。
AGENT_FIELDS = (
    "stage",
    "slots",
    "missing_slots",
    "current_action",
)
CLARIFICATION_FIELDS = (
    "current_main_intent",
    "current_sub_intent",
    "stage",
    "slots",
    "missing_slots",
    "current_action",
    "emotion",
)
RESPONSE_FIELDS = (
    "current_main_intent",
    "current_sub_intent",
    "stage",
    "slots",
    "confirmed_slots",
    "emotion",
    "needs_clarification",
)


def build_prompt_context(state: ConversationState, fields: tuple[str, ...]) -> dict[str, Any]:
    """从状态对象抽取「指定节点可见」的上下文切片（按节点隔离）。

    仅保留 ``fields`` 列出的、且非空的状态字段，得到一份只属于该
    节点的提示词上下文。省略空值字段以保持提示词紧凑。
    """
    ctx: dict[str, Any] = {}
    for field in fields:
        value = getattr(state, field)
        if value in _EMPTY_VALUES:
            continue
        ctx[field] = value
    return ctx


def _render_base_context(ctx: dict[str, Any]) -> str:
    """把隔离后的上下文切片渲染成提示词公共片段。

    仅渲染切片里实际存在的字段——白名单之外的字段本就不会出现在
    ``ctx`` 中，故不会泄露给 LLM。
    """
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
    if "current_action" in ctx:
        prompt += f"\n当前动作：{ctx['current_action']}"
    # 仅当情绪非中性时才透传——neutral 不携带信号，对生成无帮助。
    if "emotion" in ctx and ctx["emotion"].primary != "neutral":
        prompt += f"\n用户情绪：{ctx['emotion'].primary}"
    if ctx.get("needs_clarification"):
        prompt += "\n需要澄清：是"
    return prompt


def build_agent_system_prompt(state: ConversationState) -> str:
    """Agent 调度节点系统提示（仅工具编排/决策，不生成最终答案）。

    只做「是否调用工具」的决策：需要信息时调工具；信息已足够则什么都不输出，
    由下游环节生成最终回复。提示词刻意不使用「调度节点 / 本节点 / 回复节点」等
    内部架构术语，避免模型把内部决策过程当作回复输出给用户（见回归
    test_agent_node_does_not_leak_scheduler_monologue）。
    """
    ctx = build_prompt_context(state, AGENT_FIELDS)
    prompt = _render_base_context(ctx)
    prompt += (
        "\n\n你负责判断是否需要调用工具来获取信息以回答用户。"
        "\n- 若需要订单、物流、知识库等信息，请调用对应的工具；"
        "\n- 若信息已足够（无需调用工具），不要输出任何内容，直接结束即可。"
        "\n注意：你只做工具调用决策，绝不向用户输出任何文字，也不要输出分析或推理过程；"
        "最终回复由系统后续环节统一生成。"
    )
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
    ctx = build_prompt_context(state, CLARIFICATION_FIELDS)
    prompt = _render_base_context(ctx)
    prompt += (
        "\n\n你是客服助手，当前需要向用户追问以补全信息。"
        "\n请生成一句友好的追问话术，引导用户补充所需信息（例如缺订单号时请用户提供订单号）。"
        "只输出追问内容本身，不要包含多余解释或客套话。"
    )
    return _append_examples(prompt, examples)


def build_response_system_prompt(
    state: ConversationState, examples: str | None = None
) -> str:
    """回复生成节点的系统提示（含工具结果，要求生成友好响应）。"""
    ctx = build_prompt_context(state, RESPONSE_FIELDS)
    prompt = _render_base_context(ctx)
    # tool_result 是执行产物、供回复引用，仅在回复节点显式透传（其余节点不透传）。
    if state.tool_result:
        prompt += f"\n工具调用结果：{state.tool_result.model_dump()}"
    prompt += "\n请根据以上信息，生成友好的客服响应，语气与下方示例保持一致。"
    return _append_examples(prompt, examples)
