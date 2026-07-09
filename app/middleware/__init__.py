from __future__ import annotations

from fastapi import FastAPI

from .auth import AuthMiddleware
from .cors import setup_cors


def setup_middlewares(app: FastAPI) -> None:
    """注册所有 API 中间件：CORS + Auth token 解析。"""
    setup_cors(app)
    app.add_middleware(AuthMiddleware)
