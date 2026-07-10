from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# LLM 调用失败时的统一兜底回复
LLM_CALL_FAILED_REPLY = "抱歉，我暂时无法回答这个问题。"


def call_llm(
    llm_client: Any | None,
    llm_model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    fallback_content: str = LLM_CALL_FAILED_REPLY,
) -> dict[str, Any]:
    """调用 OpenAI 兼容 LLM，统一处理「未配置」与「调用异常」。

    返回 ``{"content": str, "tool_calls": list}``，便于 Agent 节点解析工具调用，
    也便于回复/澄清节点直接取 ``content``。

    - 未配置 ``llm_client`` / ``llm_model``：raise ``RuntimeError``（缺配置为致命错误）。
    - 调用异常 / 无 choices：返回 ``fallback_content`` 与空 ``tool_calls``，不抛异常。
    """
    if llm_client is None or not llm_model:
        raise RuntimeError(
            "LLM client is not configured; a real LLM client is required "
            "to run the agent node."
        )

    try:
        response = llm_client.chat.completions.create(
            model=llm_model,
            messages=messages,
            tools=tools if tools else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM call failed err=%r", exc)
        return {"content": fallback_content, "tool_calls": []}

    content = ""
    tool_calls: list[dict[str, Any]] = []
    if response.choices:
        message = response.choices[0].message
        content = message.content or ""
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
