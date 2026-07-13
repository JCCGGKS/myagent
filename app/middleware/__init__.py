from __future__ import annotations

from fastapi import FastAPI

from .auth import AuthMiddleware
from .cors import setup_cors
from .trace import TraceIdMiddleware


def setup_middlewares(app: FastAPI) -> None:
    """注册所有 API 中间件：CORS + Auth token 解析 + 请求级 trace_id。

    add_middleware 后添加的位于更外层，故 TraceIdMiddleware 最外，包裹整个请求，
    保证 auth / 业务日志都落在同一个 trace_id 下。
    """
    setup_cors(app)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(TraceIdMiddleware)
