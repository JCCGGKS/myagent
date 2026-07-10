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


def build_response_system_prompt(state: ConversationState) -> str:
    """回复生成节点的系统提示（含工具结果，要求生成友好响应）。"""
    prompt = _build_base_system_prompt(state)
    if state.tool_result:
        prompt += f"\n工具调用结果：{state.tool_result.model_dump()}"
    prompt += "\n请根据以上信息，生成友好的客服响应。"
    return prompt


def build_agent_system_prompt(state: ConversationState) -> str:
    """Agent 节点的系统提示（要求选择合适的工具回答问题）。"""
    prompt = _build_base_system_prompt(state)
    prompt += "\n请根据以上信息，选择合适的工具回答问题。如果用户问题不需要工具，直接回答。"
    return prompt
