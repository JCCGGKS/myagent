from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.trace import trace_span


class TraceIdMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求分配（或沿用上游 X-Trace-Id）一个 trace_id。

    写入 ContextVar，使本次请求链路上的所有日志（api / auth / rag / agent / tool）
    都带上同一个 trace_id，便于把「一次请求」完整串起来检索。无上游 id 时自动生成。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        upstream = request.headers.get("X-Trace-Id")
        with trace_span(upstream):
            return await call_next(request)
