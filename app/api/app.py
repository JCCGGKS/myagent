from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from app.agents import CustomerServiceAgent
from app.config import load_llm_config
from app.models import ChatRequest, ChatResponse, ConversationState, SessionInitRequest, SessionInitResponse
from app.services import (
    HandoffService,
    LLMIntentFallbackService,
    LogisticsService,
    OrderService,
)
from app.store import SessionStore


session_store = SessionStore()
llm_config = load_llm_config()
agent = CustomerServiceAgent(
    store=session_store,
    order_service=OrderService(),
    logistics_service=LogisticsService(),
    handoff_service=HandoffService(),
    llm_fallback_service=LLMIntentFallbackService(llm_config),
)

app = FastAPI(title="Customer Service Agent MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return agent.chat(request)


@app.post("/chat/init", response_model=SessionInitResponse)
def chat_init(request: SessionInitRequest) -> SessionInitResponse:
    """初始化会话，返回 session_id。"""
    session_id = session_store.create_session(request.user_id, request.channel)
    return SessionInitResponse(session_id=session_id)


def _event_to_sse(event: dict[str, Any]) -> str:
    """将事件字典格式化为 SSE 行。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

async def _chat_stream_generator(request: ChatRequest) -> AsyncGenerator[str, None]:
    """驱动 agent.chat_events() 产出 SSE 格式行。"""
    try:
        for event in agent.chat_events(request):
            yield _event_to_sse(event)
    except Exception as exc:
        yield _event_to_sse({"type": "error", "message": str(exc)})
        yield "event: done\ndata: {}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE 流式对话接口。

    前端使用 EventSource 或 fetch + ReadableStream 消费，
    每行格式：data: {JSON}\n\n
    """
    return StreamingResponse(
        _chat_stream_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



@app.get("/session/{session_id}", response_model=ConversationState)
def get_session(session_id: str) -> ConversationState:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
