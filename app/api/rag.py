from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from app.config.rag_config import RagConfig, get_rag_config_service
from app.dao import get_knowledge_file_dao
from app.model.knowledge import (
    KNOWLEDGE_FILE_STATUS_ERROR,
    KNOWLEDGE_FILE_STATUS_PROCESSING,
    KNOWLEDGE_FILE_STATUS_SUCCESS,
)
from app.pkgs.vector import get_qdrant_client
from app.business.rag import (
    Chunker,
    KnowledgeIngestionService,
    build_embedding_client,
)
from app.utils import log_error, log_info, log_warning


def _serialize_knowledge_file(record: dict[str, Any]) -> dict[str, Any]:
    """将 DAO 记录序列化为接口返回结构（时间统一转 ISO 字符串）。"""
    created_at = record.get("created_at")
    updated_at = record.get("updated_at")
    return {
        "id": record["id"],
        "user_id": record["user_id"],
        "filename": record["filename"],
        "file_size": record["file_size"],
        "doc_type": record["doc_type"],
        "chunk_count": record["chunk_count"],
        "status": record["status"],
        "error_message": record.get("error_message"),
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


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
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = "faq",
) -> dict[str, Any]:
    current_user = request.state.user
    """知识库文件上传接口（需登录，写入 user_id 到元数据）。

    文件名与后缀合法性由前端校验（仅支持 .md / .markdown / .json）。
    """
    suffix = Path(file.filename).suffix.lower()

    raw_bytes = await file.read()
    file_size = len(raw_bytes)
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

    # 先落文件元信息记录（处理中），id 作为 doc_id 透传入库，便于按文档删向量
    file_dao = get_knowledge_file_dao()
    record = file_dao.create(
        user_id=current_user.id,
        filename=file.filename,
        file_size=file_size,
        doc_type=doc_type,
        status=KNOWLEDGE_FILE_STATUS_PROCESSING,
    )
    doc_id = record["id"]

    ingestion = _build_ingestion_service()

    # 向量化未启用（缺 embedding 配置）时直接判失败，避免显示“成功但 0 向量”的误导状态
    if ingestion.embedding_client is None:
        file_dao.update_status(
            doc_id,
            KNOWLEDGE_FILE_STATUS_ERROR,
            error_message="向量化未启用：缺少 embedding.api_key 配置，未写入任何向量",
        )
        raise HTTPException(
            status_code=400,
            detail="向量化未启用：请在配置中填写 embedding.api_key（及可达的 qdrant 地址）",
        )

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
            chunk_count = ingestion.ingest_json_records(
                records, doc_type=doc_type, user_id=current_user.id, doc_id=doc_id
            )
        else:
            chunk_count = ingestion.ingest_markdown_text(
                content, doc_type=doc_type, source=file.filename,
                user_id=current_user.id, doc_id=doc_id,
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
        file_dao.update_status(doc_id, KNOWLEDGE_FILE_STATUS_ERROR, error_message=str(exc))
        raise

    file_dao.update_status(doc_id, KNOWLEDGE_FILE_STATUS_SUCCESS, chunk_count=chunk_count)
    log_info(
        "rag",
        "knowledge_upload success user=%s file=%s doc_type=%s chunk_count=%d",
        current_user.id,
        file.filename,
        doc_type,
        chunk_count,
    )
    return _serialize_knowledge_file(file_dao.get_by_id(doc_id))


@router.get("/knowledge/files")
def list_knowledge_files(
    request: Request,
) -> list[dict[str, Any]]:
    current_user = request.state.user
    """列出当前用户的知识库文件（按上传时间倒序，已软删除项除外）。"""
    file_dao = get_knowledge_file_dao()
    records = file_dao.list_by_user(current_user.id)
    return [_serialize_knowledge_file(r) for r in records]


@router.delete("/knowledge/files/{file_id}")
def delete_knowledge_file(
    file_id: int,
    request: Request,
) -> dict[str, Any]:
    current_user = request.state.user
    """删除知识库文件（软删除元信息 + 清理 Qdrant 向量，需归属当前用户）。"""
    file_dao = get_knowledge_file_dao()
    record = file_dao.get_by_id(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    if record["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除该文件")

    # 清理该文档的全部向量（按 doc_id 过滤），避免脏召回
    get_qdrant_client().delete_by_doc_id(file_id)
    file_dao.delete(file_id)
    log_info("rag", "delete_knowledge_file user=%s file_id=%s", current_user.id, file_id)
    return {"id": file_id, "deleted": True}


@router.get("/rag/config", response_model=RagConfig)
def get_rag_config(
    request: Request,
) -> RagConfig:
    current_user = request.state.user
    """获取当前 RAG 检索配置（需登录）。"""
    return get_rag_config_service().get_config()


@router.put("/rag/config", response_model=RagConfig)
def update_rag_config(
    patch: dict[str, Any],
    request: Request,
) -> RagConfig:
    current_user = request.state.user
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
