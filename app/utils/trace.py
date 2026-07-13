from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

# 当前请求/链路的 trace_id。存放在 ContextVar 中，随协程/线程上下文自动传递，
# 使任意位置的日志（graph / tool / api / auth / rag）都能带上同一个 trace_id，
# 把「一次请求」完整串起来 grep。无请求上下文时取不到，记 '-'。
TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)


def set_trace_id(tid: str | None = None) -> str:
    """设置当前上下文的 trace_id；为空则自动生成 uuid4 hex。返回实际使用的 id。"""
    if not tid:
        tid = uuid.uuid4().hex
    TRACE_ID.set(tid)
    return tid


def get_trace_id() -> str | None:
    """读取当前上下文的 trace_id（无则为 None）。"""
    return TRACE_ID.get()


@contextmanager
def trace_span(tid: str | None = None) -> Iterator[str]:
    """上下文管理器：进入时写入 trace_id（沿用上游或生成），退出时还原。

    用于中间件：一次 HTTP 请求 = 一个 span，链路内所有日志共享同一 trace_id。
    """
    actual = tid or uuid.uuid4().hex
    token = TRACE_ID.set(actual)
    try:
        yield actual
    finally:
        TRACE_ID.reset(token)


class TraceIdFilter(logging.Filter):
    """给每条日志记录注入 trace_id（取不到则为 '-'），供 Formatter 使用。

    挂在 root 的 handler 上，所有经该 handler 输出的日志（含子 logger 冒泡上来的）
    都会自动带上 trace_id，无需在各处手动拼接。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True
