"""接口级幂等测试：POST /knowledge/upload 同内容重复上传不重复向量化。

直接用 `knowledge_upload` 协程 + 共享 MemoryKnowledgeFileDAO 实例验证状态机分流，
避免依赖真实 MySQL / Qdrant / Embedding。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from app.api import rag as rag_module
from app.dao import MemoryKnowledgeFileDAO
from app.model.knowledge import (
    KNOWLEDGE_FILE_STATUS_ERROR,
    KNOWLEDGE_FILE_STATUS_PROCESSING,
    KNOWLEDGE_FILE_STATUS_SUCCESS,
)


def _hash(user_id: int, content: str) -> str:
    return hashlib.sha256(f"{user_id}:{content}".encode("utf-8")).hexdigest()


def _make_request(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id=user_id)))


def _make_file(filename: str, content: str) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content.encode("utf-8")))


def _fake_config() -> SimpleNamespace:
    """bm25 策略：无需 embedding，避免真实向量模型依赖。"""
    return SimpleNamespace(
        retrieval_strategy="bm25",
        chunk_size=512,
        chunk_overlap=64,
        min_chunk_size=32,
    )


@pytest.fixture
def env(monkeypatch):
    dao = MemoryKnowledgeFileDAO()
    qdrant = MagicMock()
    qdrant.collection_name = "test"
    qdrant.vector_size = 4

    monkeypatch.setattr(rag_module, "get_knowledge_file_dao", lambda: dao)
    monkeypatch.setattr(rag_module, "get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr(
        rag_module, "get_rag_config_service", lambda: SimpleNamespace(get_config=_fake_config)
    )
    monkeypatch.setattr(rag_module, "build_embedding_client", lambda: None)
    return SimpleNamespace(dao=dao, qdrant=qdrant)


def test_duplicate_upload_is_idempotent(env):
    content = "# 退款政策\n\n七天无理由退货。"

    first = asyncio.run(rag_module.knowledge_upload(_make_request(), _make_file("a.md", content), "faq"))
    second = asyncio.run(rag_module.knowledge_upload(_make_request(), _make_file("a.md", content), "faq"))

    # 第二次命中已有 SUCCESS 记录，跳过向量化
    assert second["duplicated"] is True
    assert second["id"] == first["id"]
    # qdrant 仅向量化一次（同内容只入库一次）
    assert env.qdrant.upsert.call_count == 1


def test_processing_duplicate_returns_409(env):
    content = "# 物流说明\n\n时效说明。"
    # 预置一条 PROCESSING 的同内容记录（模拟并发在途上传）
    h = _hash(1, content)
    asyncio.run(
        env.dao.create(
            1, "b.md", len(content), "faq",
            status=KNOWLEDGE_FILE_STATUS_PROCESSING, content_hash=h,
        )
    )
    with pytest.raises(Exception) as exc:
        asyncio.run(rag_module.knowledge_upload(_make_request(), _make_file("b.md", content), "faq"))
    assert exc.value.status_code == 409


def test_error_record_is_reused_on_retry(env):
    content = "# 常见问题\n\n如何修改地址。"
    h = _hash(1, content)
    err = asyncio.run(
        env.dao.create(
            1, "c.md", len(content), "faq",
            status=KNOWLEDGE_FILE_STATUS_ERROR, content_hash=h,
        )
    )
    result = asyncio.run(rag_module.knowledge_upload(_make_request(), _make_file("c.md", content), "faq"))

    # 复用同一记录，状态回到 SUCCESS，未新建记录
    assert result["duplicated"] is False
    assert result["id"] == err["id"]
    assert result["status"] == KNOWLEDGE_FILE_STATUS_SUCCESS
    # 重试前清掉可能残留的向量
    env.qdrant.delete_by_doc_id.assert_called_once_with(err["id"])
    assert env.qdrant.upsert.call_count == 1


def test_reupload_after_delete_allowed(env):
    content = "# 政策\n\n可删除后重传。"
    h = _hash(1, content)
    rec = asyncio.run(
        env.dao.create(
            1, "d.md", len(content), "faq",
            status=KNOWLEDGE_FILE_STATUS_SUCCESS, content_hash=h,
        )
    )
    asyncio.run(env.dao.delete(rec["id"]))  # 软删除同时清空 content_hash，释放唯一约束槽位

    # 删除后可重新上传相同内容（不会因唯一约束冲突）
    result = asyncio.run(rag_module.knowledge_upload(_make_request(), _make_file("d.md", content), "faq"))
    assert result["duplicated"] is False
    assert result["id"] != rec["id"]
    assert env.qdrant.upsert.call_count == 1

