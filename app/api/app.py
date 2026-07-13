from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.middleware import setup_middlewares
from app.api.rag import router as rag_router
from app.utils import render_metrics

app = FastAPI(title="Customer Service Agent MVP", version="0.1.0")
setup_middlewares(app)

app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(rag_router)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus 抓取端点（自托管，数据不出本机）。已在 auth 中间件放行。"""
    data, media_type = render_metrics()
    return Response(content=data, media_type=media_type)
