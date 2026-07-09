from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import File, HTTPException, UploadFile
from fastapi import APIRouter

from app.config import load_llm_config
from app.config.rag_config import RagConfig, get_rag_config_service
from app.dao import KnowledgeStore
from app.pkgs.vector import QdrantClient, get_qdrant_client
from app.business.rag import (
    Chunker,
    EmbeddingClient,
    KnowledgeIngestionService,
)


def _build_ingestion_service() -> KnowledgeIngestionService:
    """根据配置构建知识库入库服务。"""
    qdrant_client = get_qdrant_client()
    rag_config = getattr(load_llm_config(), "rag", None) or {}
    embedding_cfg = rag_config.get("embedding", {})
    embedding_client = None
    if embedding_cfg.get("api_key"):
        embedding_client = EmbeddingClient(
            model=embedding_cfg.get("model", "text-embedding-v4"),
            api_key=embedding_cfg.get("api_key", ""),
            base_url=getattr(load_llm_config(), "base_url", "") or "",
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


router = APIRouter(tags=["knowledge"])


@router.post("/knowledge/upload")
async def knowledge_upload(
    file: UploadFile = File(...),
    doc_type: str = "faq",
) -> dict[str, Any]:
    """知识库文件上传接口。

    支持格式：.md / .markdown / .json。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".md", ".markdown", ".json"}:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}，仅支持 .md / .markdown / .json",
        )

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


@router.get("/rag/config", response_model=RagConfig)
def get_rag_config() -> RagConfig:
    """获取当前 RAG 检索配置。"""
    return get_rag_config_service().get_config()


@router.put("/rag/config", response_model=RagConfig)
def update_rag_config(patch: dict[str, Any]) -> RagConfig:
    """更新 RAG 检索配置（局部更新，写回配置文件）。"""
    return get_rag_config_service().update_config(patch)
