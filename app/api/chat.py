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
    RefundService,
)
from app.config import load_llm_config
from app.business.dialog import SessionService, get_session_service
from app.pkgs.llm import build_async_openai_client
from app.schema import (
    ChatRequest,
    ChatResponse,
    SessionRenameRequest,
)
from app.utils import log_error, log_info, log_warning

session_service: SessionService = get_session_service()
llm_config = load_llm_config()
llm_client = build_async_openai_client(llm_config)
agent = CustomerServiceAgent(
    store=session_service,
    order_service=OrderService(),
    logistics_service=LogisticsService(),
    handoff_service=HandoffService(),
    refund_service=RefundService(),
    llm_fallback_service=LLMIntentFallbackService(llm_config),
    llm_client=llm_client,
    llm_model=llm_config.model if llm_client is not None else None,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    http_request: Request,
    request: ChatRequest,
) -> ChatResponse:
    user_id = http_request.state.user.id
    # 先登记会话归属：即使本次 agent 执行失败未落库，会话也已存在，
    # 后续 rename / get_messages / delete 不会因找不到会话而 404。
    await session_service.ensure_session(request.session_id, user_id, request.channel)
    return await agent.chat(request, user_id=user_id)


def _event_to_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _chat_stream_generator(request: ChatRequest, user_id: int) -> AsyncGenerator[str, None]:
    # 先登记会话归属：即使后续 agent 执行失败未落库，会话也已存在，
    # 前端仍可正常 rename / get_messages / delete。
    await session_service.ensure_session(request.session_id, user_id, request.channel)
    try:
        async for event in agent.chat_events(request, user_id=user_id):
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
async def list_sessions(
    http_request: Request,
) -> list[dict[str, Any]]:
    """列出当前 token 用户的历史会话（含 title / updated_at）。"""
    user_id = http_request.state.user.id
    return await session_service.list_sessions(user_id)


@router.get("/session/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    http_request: Request,
) -> list[dict[str, Any]]:
    """读取某会话的历史消息，必须属于当前 token 用户。"""
    user_id = http_request.state.user.id
    # upsert：会话不存在则先以当前用户归属建立（如未聊天的会话），存在则不覆盖。
    await session_service.ensure_session(session_id, user_id)
    owner_id = await session_service.get_owner(session_id)
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
    return await session_service.get_messages(session_id)


@router.put("/session/{session_id}")
async def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    http_request: Request,
) -> dict[str, str]:
    """重命名会话，必须属于当前 token 用户。"""
    user_id = http_request.state.user.id
    # upsert：未聊天的会话（前端已建但后端尚无记录）亦可改名，先以当前用户归属建立。
    await session_service.ensure_session(session_id, user_id)
    owner_id = await session_service.get_owner(session_id)
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
    await session_service.rename(session_id, body.title)
    log_info("api", "rename_session success session=%s user=%s title=%r", session_id, user_id, body.title)
    return {"session_id": session_id, "title": body.title}


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    http_request: Request,
) -> dict[str, str]:
    """软删除会话，必须属于当前 token 用户。"""
    user_id = http_request.state.user.id
    # upsert：会话不存在则先以当前用户归属建立，存在则不覆盖。
    await session_service.ensure_session(session_id, user_id)
    owner_id = await session_service.get_owner(session_id)
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
    await session_service.delete(session_id)
    log_info("api", "delete_session success session=%s user=%s", session_id, user_id)
    return {"session_id": session_id, "status": "deleted"}
