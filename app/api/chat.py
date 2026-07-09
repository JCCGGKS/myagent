from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.responses import StreamingResponse

from app.business import (
    CustomerServiceAgent,
    HandoffService,
    LLMIntentFallbackService,
    LogisticsService,
    OrderService,
)
from app.business.auth.deps import resolve_user_id
from app.config import load_llm_config
from app.dao import SessionStore, get_session_store
from app.schema import (
    ChatRequest,
    ChatResponse,
    ConversationState,
    SessionInitRequest,
    SessionInitResponse,
    SessionRenameRequest,
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


@router.post("", response_model=ChatResponse)
def chat(
    http_request: Request,
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> ChatResponse:
    user_id = resolve_user_id(http_request, authorization)
    return agent.chat(request, user_id=user_id)


@router.post("/init", response_model=SessionInitResponse)
def chat_init(
    http_request: Request,
    request: SessionInitRequest,
    authorization: str | None = Header(default=None),
) -> SessionInitResponse:
    """初始化会话，返回 session_id。user_id 必须来自 token。"""
    user_id = resolve_user_id(http_request, authorization)
    session_id = session_store.create_session(user_id, request.channel, request.title)
    return SessionInitResponse(session_id=session_id, title=request.title)


def _event_to_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _chat_stream_generator(request: ChatRequest, user_id: int) -> AsyncGenerator[str, None]:
    try:
        for event in agent.chat_events(request, user_id=user_id):
            yield _event_to_sse(event)
    except Exception as exc:
        yield _event_to_sse({"type": "error", "message": str(exc)})
        yield "event: done\ndata: {}\n\n"


@router.post("/stream")
async def chat_stream(
    http_request: Request,
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    user_id = resolve_user_id(http_request, authorization)
    return StreamingResponse(
        _chat_stream_generator(request, user_id=user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
def list_sessions(
    http_request: Request,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """列出当前 token 用户的历史会话（含 title / updated_at / preview）。"""
    user_id = resolve_user_id(http_request, authorization=authorization)
    return session_store.list_sessions(user_id)


@router.get("/session/{session_id}", response_model=ConversationState)
def get_session(
    session_id: str,
    http_request: Request,
    authorization: str | None = Header(default=None),
) -> ConversationState:
    """获取某会话状态，必须属于当前 token 用户。"""
    user_id = resolve_user_id(http_request, authorization=authorization)
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session


@router.get("/session/{session_id}/messages")
def get_session_messages(
    session_id: str,
    http_request: Request,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """读取某会话的历史消息，必须属于当前 token 用户。"""
    user_id = resolve_user_id(http_request, authorization=authorization)
    owner_id = session_store.get_user_id(session_id)
    if owner_id is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session_store.get_messages(session_id)


@router.put("/session/{session_id}")
def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    http_request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """重命名会话，必须属于当前 token 用户。"""
    user_id = resolve_user_id(http_request, authorization=authorization)
    owner_id = session_store.get_user_id(session_id)
    if owner_id is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    session_store.update_title(session_id, body.title)
    return {"session_id": session_id, "title": body.title}


@router.delete("/session/{session_id}")
def delete_session(
    session_id: str,
    http_request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """软删除会话，必须属于当前 token 用户。"""
    user_id = resolve_user_id(http_request, authorization=authorization)
    owner_id = session_store.get_user_id(session_id)
    if owner_id is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    session_store.delete_session(session_id)
    return {"session_id": session_id, "status": "deleted"}
