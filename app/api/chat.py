from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.business import (
    CustomerServiceAgent,
    HandoffService,
    LLMIntentFallbackService,
    LogisticsService,
    OrderService,
)
from app.config import load_llm_config
from app.dao import SessionStore, get_session_store
from app.pkgs.llm import build_openai_client
from app.schema import (
    ChatRequest,
    ChatResponse,
    ConversationState,
    SessionInitRequest,
    SessionInitResponse,
    SessionRenameRequest,
)
from app.utils import log_error, log_info, log_warning

session_store: SessionStore = get_session_store()
llm_config = load_llm_config()
llm_client = build_openai_client(llm_config)
agent = CustomerServiceAgent(
    store=session_store,
    order_service=OrderService(),
    logistics_service=LogisticsService(),
    handoff_service=HandoffService(),
    llm_fallback_service=LLMIntentFallbackService(llm_config),
    llm_client=llm_client,
    llm_model=llm_config.model if llm_client is not None else None,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    http_request: Request,
    request: ChatRequest,
) -> ChatResponse:
    user_id = http_request.state.user.id
    return agent.chat(request, user_id=user_id)


@router.post("/init", response_model=SessionInitResponse)
def chat_init(
    http_request: Request,
    request: SessionInitRequest,
) -> SessionInitResponse:
    """初始化会话，返回 session_id。user_id 必须来自 token。"""
    user_id = http_request.state.user.id
    session_id = session_store.create_session(user_id, request.channel, request.title)
    log_info("api", "chat_init success session=%s user=%s channel=%s", session_id, user_id, request.channel)
    return SessionInitResponse(session_id=session_id, title=request.title)


def _event_to_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _chat_stream_generator(request: ChatRequest, user_id: int) -> AsyncGenerator[str, None]:
    try:
        for event in agent.chat_events(request, user_id=user_id):
            yield _event_to_sse(event)
    except Exception as exc:
        log_error(
            "api",
            "chat_stream crashed session=%s user=%s err=%r",
            request.session_id,
            user_id,
            exc,
        )
        yield _event_to_sse({"type": "error", "message": str(exc)})
        yield "event: done\ndata: {}\n\n"


@router.post("/stream")
async def chat_stream(
    http_request: Request,
    request: ChatRequest,
) -> StreamingResponse:
    user_id = http_request.state.user.id
    return StreamingResponse(
        _chat_stream_generator(request, user_id),
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
) -> list[dict[str, Any]]:
    """列出当前 token 用户的历史会话（含 title / updated_at）。"""
    user_id = http_request.state.user.id
    return session_store.list_sessions(user_id)


@router.get("/session/{session_id}/messages")
def get_session_messages(
    session_id: str,
    http_request: Request,
) -> list[dict[str, Any]]:
    """读取某会话的历史消息，必须属于当前 token 用户。"""
    user_id = http_request.state.user.id
    owner_id = session_store.get_user_id(session_id)
    if owner_id is None:
        log_warning("api", "get_session_messages not_found session=%s user=%s", session_id, user_id)
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_id != user_id:
        log_warning(
            "api",
            "get_session_messages forbidden session=%s owner=%s requester=%s",
            session_id,
            owner_id,
            user_id,
        )
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session_store.get_messages(session_id)


@router.put("/session/{session_id}")
def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    http_request: Request,
) -> dict[str, str]:
    """重命名会话，必须属于当前 token 用户。"""
    user_id = http_request.state.user.id
    owner_id = session_store.get_user_id(session_id)
    if owner_id is None:
        log_warning("api", "rename_session not_found session=%s user=%s", session_id, user_id)
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_id != user_id:
        log_warning(
            "api",
            "rename_session forbidden session=%s owner=%s requester=%s",
            session_id,
            owner_id,
            user_id,
        )
        raise HTTPException(status_code=403, detail="无权访问该会话")
    session_store.update_title(session_id, body.title)
    log_info("api", "rename_session success session=%s user=%s title=%r", session_id, user_id, body.title)
    return {"session_id": session_id, "title": body.title}


@router.delete("/session/{session_id}")
def delete_session(
    session_id: str,
    http_request: Request,
) -> dict[str, str]:
    """软删除会话，必须属于当前 token 用户。"""
    user_id = http_request.state.user.id
    owner_id = session_store.get_user_id(session_id)
    if owner_id is None:
        log_warning("api", "delete_session not_found session=%s user=%s", session_id, user_id)
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_id != user_id:
        log_warning(
            "api",
            "delete_session forbidden session=%s owner=%s requester=%s",
            session_id,
            owner_id,
            user_id,
        )
        raise HTTPException(status_code=403, detail="无权访问该会话")
    session_store.delete_session(session_id)
    log_info("api", "delete_session success session=%s user=%s", session_id, user_id)
    return {"session_id": session_id, "status": "deleted"}
