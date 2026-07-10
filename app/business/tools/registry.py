"""工具 schema 注册中心。

所有工具的 schema 集中在 ``app.business.tools.tool_executor.TOOLS`` 中
（schema + handler 一一对应）。本模块只作为对外 façade，返回供 LLM
function calling 使用的 ``tools`` 载荷列表。

新增工具：在 ``TOOLS`` 中加一项并实现对应 handler 即可，无需改动此处。
"""

from __future__ import annotations

from typing import Any

from app.business.tools.tool_executor import TOOL_SCHEMAS


def build_tool_schemas() -> list[dict[str, Any]]:
    """汇总所有已注册工具的 OpenAI tools schema。"""
    return list(TOOL_SCHEMAS.values())
