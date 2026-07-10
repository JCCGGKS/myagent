from __future__ import annotations

from app.schema import ConversationState

SYSTEM_PROMPT_PREFIX = "你是一个客服助手，负责回答用户问题。"


def _build_base_system_prompt(state: ConversationState) -> str:
    """构造系统提示的公共部分（意图、阶段、槽位等上下文）。"""
    prompt = SYSTEM_PROMPT_PREFIX
    prompt += f"\n当前意图：{state.current_main_intent}.{state.current_sub_intent}"
    prompt += f"\n当前阶段：{state.stage}"
    if state.slots:
        prompt += f"\n已填槽位：{state.slots}"
    if state.missing_slots:
        prompt += f"\n缺失槽位：{state.missing_slots}"
    return prompt


def build_agent_system_prompt(state: ConversationState) -> str:
    """Agent 节点系统提示（仅工具编排/决策，不生成最终答案）。

    明确告知 LLM：本节点负责判断是否调用工具获取信息；
    当已有足够信息（无需再调用工具）时，结束本节点、由回复节点生成最终答案。
    """
    prompt = _build_base_system_prompt(state)
    prompt += (
        "\n\n你是客服助手的【调度节点】，只负责决定下一步动作："
        "\n1. 若需要更多信息来回答用户（如订单状态、物流、知识库内容），请调用合适的工具；"
        "\n2. 若当前上下文已足够回答用户，请不要调用任何工具，直接结束本节点。"
        "\n注意：你只做决策与工具调用，不要在此输出给用户的最终回复，最终回复由专门的回复节点生成。"
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
    prompt = _build_base_system_prompt(state)
    prompt += (
        "\n\n你是客服助手，当前需要向用户追问以补全信息。"
        f"\n当前动作：{state.current_action}"
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
    if state.tool_result:
        prompt += f"\n工具调用结果：{state.tool_result.model_dump()}"
    prompt += "\n请根据以上信息，生成友好的客服响应，语气与下方示例保持一致。"
    return _append_examples(prompt, examples)
