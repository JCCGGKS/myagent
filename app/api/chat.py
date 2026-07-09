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


def get_user_id_from_token(authorization: str | None) -> int | None:
    """从 Authorization Bearer token 中解析 int 类型的 user_id。"""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token, expected_purpose="access")
            user_id = payload.get("user_id")
            if user_id is not None:
                return int(user_id)
        except Exception:
            pass
    return None


def get_request_user(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> int:
    """解析当前请求的最终 user_id（int）。

    规则：
    - 携带可解析的 Authorization Bearer token → 以 token 内 user_id 为准（int）。
    - 无 token / 解析失败 → 回退使用请求体中的 user_id。
    """
    token_uid = get_user_id_from_token(authorization)
    if token_uid is not None:
        return token_uid
    if request.user_id:
        return request.user_id
    raise HTTPException(status_code=401, detail="Missing user_id (provide Authorization token or user_id)")


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    request.user_id = get_request_user(request, authorization)
    return agent.chat(request)


@router.post("/init", response_model=SessionInitResponse)
def chat_init(request: SessionInitRequest, authorization: str | None = Header(default=None)) -> SessionInitResponse:
    """初始化会话，返回 session_id。user_id 优先取自 token。"""
    token_uid = get_user_id_from_token(authorization)
    if token_uid is not None:
        request.user_id = token_uid
    if not request.user_id:
        raise HTTPException(status_code=401, detail="Missing user_id (provide Authorization token or user_id)")
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


@router.get("/sessions")
def list_sessions(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    """列出当前 token 用户的历史会话（含 title / updated_at / preview），按更新时间倒序。"""
    user_id = get_user_id_from_token(authorization)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    return session_store.list_sessions(user_id)


@router.get("/session/{session_id}/messages")
def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """读取某会话的历史消息（role / content），按发送顺序。"""
    return session_store.get_messages(session_id)


@router.put("/session/{session_id}")
def rename_session(session_id: str, body: SessionRenameRequest) -> dict[str, str]:
    """重命名会话。"""
    session_store.update_title(session_id, body.title)
    return {"session_id": session_id, "title": body.title}


@router.delete("/session/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    """删除会话（级联清理子表）。"""
    session_store.delete_session(session_id)
    return {"session_id": session_id, "status": "deleted"}
