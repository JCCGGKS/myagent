from __future__ import annotations

from typing import Any

from app.config.llm import LLMConfig


def build_openai_client(config: LLMConfig) -> Any:
    """构建 OpenAI 兼容客户端（同步，配置了 api_key 才可用）。"""
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


def build_async_openai_client(config: LLMConfig) -> Any | None:
    """构建 OpenAI 兼容异步客户端（AsyncOpenAI）。

    用于全异步链路：HTTP 请求在 asyncio 事件循环内 await，I/O 等待时让出
    事件循环，避免阻塞单进程内的其他请求（详见 plans/full-async-plan.md）。
    未配置 api_key 时返回 None。
    """
    try:
        from openai import AsyncOpenAI
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
    return AsyncOpenAI(**kwargs)
