from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from app.config.rag_config import RagConfig, get_rag_config_service
from app.dao import get_knowledge_file_dao
from app.dao.knowledge_file import DuplicateKnowledgeFileError
from app.model.knowledge import (
    KNOWLEDGE_FILE_STATUS_ERROR,
    KNOWLEDGE_FILE_STATUS_PROCESSING,
    KNOWLEDGE_FILE_STATUS_SUCCESS,
)
from app.pkgs.vector import get_qdrant_client
from app.business.rag import (
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
        "content_hash": record.get("content_hash"),
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


class _IdempotentHit(Exception):
    """幂等命中（同内容已 SUCCESS）：携带已有记录，由调用方直接返回。"""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("idempotent hit")
        self.result = result


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
        embedding_client=embedding_client,
        collection_name=qdrant_client.collection_name,
        vector_size=qdrant_client.vector_size,
        chunk_size=rag_config.chunk_size,
        chunk_overlap=rag_config.chunk_overlap,
        min_chunk_size=rag_config.min_chunk_size,
    )


def _delete_vectors(doc_id: int) -> None:
    """清理某文档的全部 Qdrant 向量（按 doc_id）。删除 / 更新接口共用。"""
    get_qdrant_client().delete_by_doc_id(doc_id)


async def _ingest_document(
    file_dao: Any,
    doc_id: int,
    content: str,
    filename: str,
    doc_type: str,
    user_id: int,
    refresh_created_at: bool = False,
) -> int:
    """对 doc_id 做向量化入库并落最终状态，返回 chunk_count。

    上传（新记录 / 重传 / 失败重试）与更新（重建向量）共用的核心步骤：
    - 检索策略预检失败 → 置 ERROR + 抛 400；
    - 向量化异常 → 置 ERROR + 上抛；
    - 成功 → 置 SUCCESS 并记录 chunk_count。

    ``refresh_created_at`` 为 True 时（仅上传接口在错误分支使用），落 ERROR 同时
    刷新 created_at 为当前时间，使失败的上传在列表中按最新时间排序、方便重试定位。
    """
    ingestion = _build_ingestion_service()
    # 检索策略感知的向量模型预检：semantic/hybrid 需向量模型，否则提前拦截
    if (
        get_rag_config_service().get_config().retrieval_strategy in ("semantic", "hybrid")
        and ingestion.embedding_client is None
    ):
        await file_dao.update_status(
            doc_id,
            KNOWLEDGE_FILE_STATUS_ERROR,
            error_message="选择的检索策略需要配置向量模型",
            refresh_created_at=refresh_created_at,
        )
        raise HTTPException(status_code=400, detail="选择的检索策略需要配置向量模型")

    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".json":
            try:
                records = json.loads(content)
            except json.JSONDecodeError:
                log_warning("rag", "ingest json_decode_failed user=%s file=%s", user_id, filename)
                raise HTTPException(status_code=400, detail="JSON 解析失败")
            if not isinstance(records, list):
                records = [records]
            chunk_count = ingestion.ingest_json_records(
                records, doc_type=doc_type, user_id=user_id, doc_id=doc_id
            )
        else:
            # 非 JSON 文本：按所选文档类型（doc_type 即格式）取对应分块策略
            chunk_count = ingestion.ingest_text(
                content, doc_type=doc_type, doc_format=doc_type,
                source=filename, user_id=user_id, doc_id=doc_id,
            )
    except HTTPException:
        raise
    except Exception as exc:
        log_error("rag", "ingest crashed user=%s file=%s err=%r", user_id, filename, exc)
        await file_dao.update_status(
            doc_id,
            KNOWLEDGE_FILE_STATUS_ERROR,
            error_message=str(exc),
            refresh_created_at=refresh_created_at,
        )
        raise

    await file_dao.update_status(doc_id, KNOWLEDGE_FILE_STATUS_SUCCESS, chunk_count=chunk_count)
    log_info(
        "rag", "ingest success user=%s file=%s doc_type=%s chunk_count=%d",
        user_id, filename, doc_type, chunk_count,
    )
    return chunk_count


router = APIRouter(tags=["knowledge"])


@router.post("/knowledge/upload")
async def knowledge_upload(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
) -> dict[str, Any]:
    current_user = request.state.user
    """知识库文件上传接口（需登录，写入 user_id 到元数据）。

    文件名与后缀合法性、后缀与 doc_type 一致性由前端校验
    （支持 .md / .markdown / .json / .word / .excel / .csv / .pdf / .ppt）；
    后端按所选文档类型路由到对应分块策略，未知格式回退 DefaultTextStrategy。
    """

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

    # 幂等键：user_id + 文件内容（严格按内容去重，doc_type 不入哈希）。
    # 同用户上传相同内容 → 命中已有记录，跳过向量化，避免重复向量与冗余记录。
    content_hash = hashlib.sha256(
        f"{current_user.id}:{content}".encode("utf-8")
    ).hexdigest()

    file_dao = get_knowledge_file_dao()

    async def _acquire_from_existing(existing: dict[str, Any]) -> int:
        """按幂等状态机复用已有记录，返回本次要处理的 doc_id。

        - SUCCESS：已处理完成，抛出 _IdempotentHit 由调用方直接返回（跳过向量化）；
        - PROCESSING：同内容正在处理，抛 409 防并发重复；
        - ERROR：复用该记录重试，先清掉可能残留的向量。
        """
        if existing["status"] == KNOWLEDGE_FILE_STATUS_SUCCESS:
            result = _serialize_knowledge_file(existing)
            result["duplicated"] = True
            raise _IdempotentHit(result)
        if existing["status"] == KNOWLEDGE_FILE_STATUS_PROCESSING:
            raise HTTPException(status_code=409, detail="相同文件正在处理中，请勿重复上传")
        doc_id = existing["id"]
        _delete_vectors(doc_id)  # 清除可能残留的向量
        await file_dao.update_status(doc_id, KNOWLEDGE_FILE_STATUS_PROCESSING)
        return doc_id

    existing = await file_dao.find_by_content_hash(current_user.id, content_hash)
    if existing is not None:
        try:
            doc_id = await _acquire_from_existing(existing)
        except _IdempotentHit as hit:
            return hit.result
    else:
        try:
            record = await file_dao.create(
                user_id=current_user.id,
                filename=file.filename,
                file_size=file_size,
                doc_type=doc_type,
                status=KNOWLEDGE_FILE_STATUS_PROCESSING,
                content_hash=content_hash,
            )
            doc_id = record["id"]
        except DuplicateKnowledgeFileError:
            # 并发同内容上传：唯一约束兜底，回退到已有记录按状态机分流
            existing = await file_dao.find_by_content_hash(current_user.id, content_hash)
            if existing is None:
                raise
            try:
                doc_id = await _acquire_from_existing(existing)
            except _IdempotentHit as hit:
                return hit.result

    # 向量化入库 + 落最终状态（上传/重传/失败重试共用核心步骤）
    # 错误分支刷新 created_at，使失败上传在列表中按最新时间排序
    await _ingest_document(
        file_dao, doc_id, content, file.filename, doc_type, current_user.id,
        refresh_created_at=True,
    )
    result = _serialize_knowledge_file(await file_dao.get_by_id(doc_id))
    result["duplicated"] = False
    return result


@router.get("/knowledge/files")
async def list_knowledge_files(
    request: Request,
) -> list[dict[str, Any]]:
    current_user = request.state.user
    """列出当前用户的知识库文件（按上传时间倒序，已软删除项除外）。"""
    file_dao = get_knowledge_file_dao()
    records = await file_dao.list_by_user(current_user.id)
    return [_serialize_knowledge_file(r) for r in records]


@router.delete("/knowledge/files/{file_id}")
async def delete_knowledge_file(
    file_id: int,
    request: Request,
) -> dict[str, Any]:
    current_user = request.state.user
    """删除知识库文件（软删除元信息 + 清理 Qdrant 向量，需归属当前用户）。"""
    file_dao = get_knowledge_file_dao()
    record = await file_dao.get_by_id(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    if record["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除该文件")

    # 清理该文档的全部向量（按 doc_id 过滤），避免脏召回
    _delete_vectors(file_id)
    await file_dao.delete(file_id)
    log_info("rag", "delete_knowledge_file user=%s file_id=%s", current_user.id, file_id)
    return {"id": file_id, "deleted": True}


@router.put("/knowledge/files/{file_id}")
async def update_knowledge_file(
    file_id: int,
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
) -> dict[str, Any]:
    current_user = request.state.user
    """更新已上传的知识库文件：删除旧向量 + 重新向量化（重建），并刷新上传时间(updated_at)。

    同一 file_id 复用：文档标识 doc_id 不变；内容若变化则同步更新 content_hash 以保持幂等键一致。
    若更新后的内容与其他已上传文件重复（非自身），返回 409 由调用方直接复用。
    """
    file_dao = get_knowledge_file_dao()
    record = await file_dao.get_by_id(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    if record["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="无权更新该文件")

    raw_bytes = await file.read()
    file_size = len(raw_bytes)
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        log_warning("rag", "update_knowledge_file non_utf8 user=%s file=%s", current_user.id, file.filename)
        raise HTTPException(status_code=400, detail="文件编码非 UTF-8，无法解析")

    # 幂等键：与上传一致（user_id + 内容）
    content_hash = hashlib.sha256(
        f"{current_user.id}:{content}".encode("utf-8")
    ).hexdigest()

    # 若新内容与其他已上传文件重复（非自身），直接冲突返回，避免重建后撞唯一键
    other = await file_dao.find_by_content_hash(current_user.id, content_hash)
    if other is not None and other["id"] != file_id:
        raise HTTPException(
            status_code=409,
            detail="更新后的内容与其他已上传文件重复，请直接复用该文件",
        )

    # 1) 同步内容元信息（含新 content_hash / filename / file_size / doc_type），刷新上传时间
    try:
        await file_dao.update_content(file_id, content_hash, file.filename, file_size, doc_type)
    except DuplicateKnowledgeFileError:
        raise HTTPException(status_code=409, detail="更新后的内容与其他已上传文件重复")
    # 2) 删除旧向量
    _delete_vectors(file_id)
    # 3) 置处理中（同时刷新 updated_at）
    await file_dao.update_status(file_id, KNOWLEDGE_FILE_STATUS_PROCESSING)
    # 4) 重新向量化（重建）
    await _ingest_document(file_dao, file_id, content, file.filename, doc_type, current_user.id)

    result = _serialize_knowledge_file(await file_dao.get_by_id(file_id))
    result["duplicated"] = False
    return result


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
