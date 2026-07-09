from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.responses import StreamingResponse

from app.business import (
    CustomerServiceAgent,
    HandoffService,
    LLMIntentFallbackService,
    LogisticsService,
    OrderService,
)
from app.pkgs.auth.jwt import decode_token
from app.config import load_llm_config
from app.dao import SessionStore, get_session_store
from app.schema import (
    ChatRequest,
    ChatResponse,
    ConversationState,
    SessionInitRequest,
    SessionInitResponse,
)

session_store: SessionStore = get_session_store()
llm_config = load_llm_config()
agent = CustomerServiceAgent(
    store=session_store,
    order_service=OrderService(),
    logistics_service=LogisticsService(),
    handoff_service=HandoffService(),
    llm_fallback_service=LLMIntentFallbackService(llm_config),
)

router = APIRouter(prefix="/chat", tags=["chat"])


def get_request_user(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> str:
    """解析当前请求的最终 user_id。

    规则：
    - 携带可解析的 Authorization Bearer token → 以 token 内 user_id 为准。
    - 无 token / 解析失败 → 回退使用请求体中的 user_id。
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token, expected_purpose="access")
            user_id = payload.get("user_id")
            if user_id:
                return str(user_id)
        except Exception:
            pass
    return request.user_id


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    request.user_id = get_request_user(request, authorization)
    return agent.chat(request)


@router.post("/init", response_model=SessionInitResponse)
def chat_init(request: SessionInitRequest, authorization: str | None = Header(default=None)) -> SessionInitResponse:
    """初始化会话，返回 session_id。"""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token, expected_purpose="access")
            if payload.get("user_id"):
                request.user_id = str(payload["user_id"])
        except Exception:
            pass
    session_id = session_store.create_session(request.user_id, request.channel, request.title)
    return SessionInitResponse(session_id=session_id, title=request.title)


def _event_to_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _chat_stream_generator(request: ChatRequest) -> AsyncGenerator[str, None]:
    try:
        for event in agent.chat_events(request):
            yield _event_to_sse(event)
    except Exception as exc:
        yield _event_to_sse({"type": "error", "message": str(exc)})
        yield "event: done\ndata: {}\n\n"


@router.post("/stream")
async def chat_stream(request: ChatRequest, authorization: str | None = Header(default=None)) -> StreamingResponse:
    request.user_id = get_request_user(request, authorization)
    return StreamingResponse(
        _chat_stream_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/session/{session_id}", response_model=ConversationState)
def get_session(session_id: str) -> ConversationState:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
