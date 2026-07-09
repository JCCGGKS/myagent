from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import File, HTTPException, UploadFile
from fastapi import APIRouter, Depends

from app.business.auth.deps import get_current_user
from app.business.auth.models import UserInfo
from app.config import load_llm_config
from app.config.rag_config import RagConfig, get_rag_config_service
from app.dao import KnowledgeStore
from app.pkgs.vector import QdrantClient, get_qdrant_client
from app.business.rag import (
    Chunker,
    KnowledgeIngestionService,
    build_embedding_client,
)
from app.utils import log_error, log_info, log_warning


def _build_ingestion_service() -> KnowledgeIngestionService:
    """根据配置构建知识库入库服务。

    qdrant 连接参数（host/port/collection_name/vector_size/distance）与
    embedding 配置均来自顶层配置段，由 get_qdrant_client / build_embedding_client
    读取；collection_name 与 vector_size 直接沿用 client 上已解析的值。
    切块参数（chunk_size/overlap/min_chunk_size）来自 rag 段，前端可控。
    """
    rag_config = get_rag_config_service().get_config()
    qdrant_client = get_qdrant_client()
    embedding_client = build_embedding_client()
    return KnowledgeIngestionService(
        qdrant_client=qdrant_client,
        chunker=Chunker(
            chunk_size=rag_config.chunk_size,
            chunk_overlap=rag_config.chunk_overlap,
            min_chunk_size=rag_config.min_chunk_size,
        ),
        embedding_client=embedding_client,
        collection_name=qdrant_client.collection_name,
        vector_size=qdrant_client.vector_size,
    )


router = APIRouter(tags=["knowledge"])


@router.post("/knowledge/upload")
async def knowledge_upload(
    file: UploadFile = File(...),
    doc_type: str = "faq",
    current_user: UserInfo = Depends(get_current_user),
) -> dict[str, Any]:
    """知识库文件上传接口（需登录，写入 user_id 到元数据）。

    支持格式：.md / .markdown / .json。
    """
    if not file.filename:
        log_warning("rag", "knowledge_upload missing filename user=%s", current_user.id)
        raise HTTPException(status_code=400, detail="缺少文件名")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".md", ".markdown", ".json"}:
        log_warning(
            "rag",
            "knowledge_upload unsupported_type user=%s file=%s suffix=%s",
            current_user.id,
            file.filename,
            suffix,
        )
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}，仅支持 .md / .markdown / .json",
        )

    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        log_warning(
            "rag",
            "knowledge_upload non_utf8 user=%s file=%s",
            current_user.id,
            file.filename,
        )
        raise HTTPException(status_code=400, detail="文件编码非 UTF-8，无法解析")

    ingestion = _build_ingestion_service()

    try:
        if suffix == ".json":
            try:
                records = json.loads(content)
            except json.JSONDecodeError:
                log_warning(
                    "rag",
                    "knowledge_upload json_decode_failed user=%s file=%s",
                    current_user.id,
                    file.filename,
                )
                raise HTTPException(status_code=400, detail="JSON 解析失败")
            if not isinstance(records, list):
                records = [records]
            chunk_count = ingestion.ingest_json_records(records, doc_type=doc_type, user_id=current_user.id)
        else:
            chunk_count = ingestion.ingest_markdown_text(
                content, doc_type=doc_type, source=file.filename, user_id=current_user.id
            )
    except HTTPException:
        raise
    except Exception as exc:
        log_error(
            "rag",
            "knowledge_upload crashed user=%s file=%s err=%r",
            current_user.id,
            file.filename,
            exc,
        )
        raise

    log_info(
        "rag",
        "knowledge_upload success user=%s file=%s doc_type=%s chunk_count=%d",
        current_user.id,
        file.filename,
        doc_type,
        chunk_count,
    )
    return {
        "filename": file.filename,
        "doc_type": doc_type,
        "chunk_count": chunk_count,
    }


@router.get("/rag/config", response_model=RagConfig)
def get_rag_config(
    current_user: UserInfo = Depends(get_current_user),
) -> RagConfig:
    """获取当前 RAG 检索配置（需登录）。"""
    return get_rag_config_service().get_config()


@router.put("/rag/config", response_model=RagConfig)
def update_rag_config(
    patch: dict[str, Any],
    current_user: UserInfo = Depends(get_current_user),
) -> RagConfig:
    """更新 RAG 检索配置（需登录，局部更新，写回配置文件）。"""
    try:
        result = get_rag_config_service().update_config(patch)
    except Exception as exc:
        log_error(
            "rag",
            "update_rag_config crashed user=%s patch=%s err=%r",
            current_user.id,
            patch,
            exc,
        )
        raise
    log_info("rag", "update_rag_config success user=%s patch=%s", current_user.id, patch)
    return result
