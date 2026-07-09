from __future__ import annotations

import json
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from app.agents import CustomerServiceAgent
from app.auth.deps import get_current_user
from app.auth.jwt import decode_token
from app.auth.router import router as auth_router
from app.config import load_llm_config
from app.config.rag_config import RagConfig, get_rag_config_service
from app.models import ChatRequest, ChatResponse, ConversationState, SessionInitRequest, SessionInitResponse
from app.rag import (
    Chunker,
    EmbeddingClient,
    KnowledgeIngestionService,
    QdrantClient,
)
from app.rag.qdrant_client import get_qdrant_client
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


def _build_ingestion_service() -> KnowledgeIngestionService:
    """根据配置构建知识库入库服务。"""
    qdrant_client = get_qdrant_client()
    rag_config = getattr(llm_config, "rag", None) or {}
    embedding_cfg = rag_config.get("embedding", {})
    embedding_client = None
    if embedding_cfg.get("api_key"):
        embedding_client = EmbeddingClient(
            model=embedding_cfg.get("model", "text-embedding-v4"),
            api_key=embedding_cfg.get("api_key", ""),
            base_url=getattr(llm_config, "base_url", "") or "",
            dimensions=embedding_cfg.get("dimensions", 1024),
        )
    collection = rag_config.get("qdrant", {}).get("collection_name", "customer_service_knowledge")
    return KnowledgeIngestionService(
        qdrant_client=qdrant_client,
        chunker=Chunker(),
        embedding_client=embedding_client,
        collection_name=collection,
        vector_size=embedding_cfg.get("dimensions", 1024),
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
app.include_router(auth_router)


def get_request_user(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> str:
    """解析当前请求的最终 user_id。

    规则：
    - 携带可解析的 Authorization Bearer token → 以 token 内 user_id 为准（不信任 Body）。
    - 无 token / 解析失败 → 回退使用请求体中的 user_id（向后兼容未登录对话）。
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/me")
def auth_me(user=Depends(get_current_user)) -> dict:
    """返回当前登录用户信息（需 Authorization 头）。"""
    return {"id": user.id, "username": user.username, "email": user.email}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    request.user_id = get_request_user(request, authorization)
    return agent.chat(request)


@app.post("/chat/init", response_model=SessionInitResponse)
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
async def chat_stream(request: ChatRequest, authorization: str | None = Header(default=None)) -> StreamingResponse:
    """SSE 流式对话接口。

    前端使用 EventSource 或 fetch + ReadableStream 消费，
    每行格式：data: {JSON}\n\n
    """
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



@app.get("/session/{session_id}", response_model=ConversationState)
def get_session(session_id: str) -> ConversationState:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/knowledge/upload")
async def knowledge_upload(
    file: UploadFile = File(...),
    doc_type: str = "faq",
) -> dict[str, Any]:
    """知识库文件上传接口。

    支持格式：
    - `.md` / `.markdown`：Markdown 文档，按标题结构分块后入库
    - `.json`：JSON 数组，每条记录含 `content` 字段（或其他文本字段）

    参数：
    - file: 上传的文件
    - doc_type: 文档类型（faq / policy / product / help），用于元数据过滤

    返回：
    - chunk_count: 成功写入的块数量
    - filename: 原始文件名
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".md", ".markdown", ".json"}:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}，仅支持 .md / .markdown / .json",
        )

    # 先读内容到内存（小文件场景足够）
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码非 UTF-8，无法解析")

    ingestion = _build_ingestion_service()

    if suffix == ".json":
        try:
            records = json.loads(content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="JSON 解析失败")
        if not isinstance(records, list):
            records = [records]
        chunk_count = ingestion.ingest_json_records(records, doc_type=doc_type)
    else:
        chunk_count = ingestion.ingest_markdown_text(
            content, doc_type=doc_type, source=file.filename
        )

    return {
        "filename": file.filename,
        "doc_type": doc_type,
        "chunk_count": chunk_count,
    }


@app.get("/rag/config", response_model=RagConfig)
def get_rag_config() -> RagConfig:
    """获取当前 RAG 检索配置。"""
    return get_rag_config_service().get_config()


@app.put("/rag/config", response_model=RagConfig)
def update_rag_config(patch: dict[str, Any]) -> RagConfig:
    """更新 RAG 检索配置（局部更新，写回 llm_config.local.yml）。"""
    return get_rag_config_service().update_config(patch)
