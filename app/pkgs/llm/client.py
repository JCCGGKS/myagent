from __future__ import annotations

from typing import Any

from app.config.llm import LLMConfig


def build_openai_client(config: LLMConfig) -> Any:
    """构建 OpenAI 兼容客户端（配置了 api_key 才可用）。"""
    try:
        from openai import OpenAI
    except ImportError:  # pragma: no cover
        return None

    if not config.is_usable:
        return None

    kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": config.timeout_seconds,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)
