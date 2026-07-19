"""接口级幂等测试：POST /knowledge/upload 同内容重复上传不重复向量化。

直接用 `knowledge_upload` 协程 + 共享 MemoryKnowledgeFileDAO 实例验证状态机分流，
避免依赖真实 MySQL / Qdrant / Embedding。
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, UploadFile

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

    # 入库时统一写 bm25 稀疏向量（Qdrant 原生 BM25）+ dense 稠密向量：
    # - bm25 由 build_sparse_vector 产出，单测不拉真实 FastEmbed，mock 成占位稀疏向量；
    # - dense 由 embedding_client 产出，mock 成与文本数等长、维度=4 的占位向量。
    from qdrant_client.models import SparseVector

    dummy_sparse = SparseVector(indices=[0], values=[1.0])
    monkeypatch.setattr(
        "app.business.rag.retrieval.bm25.build_sparse_vector",
        lambda text: dummy_sparse,
    )
    monkeypatch.setattr(
        "app.business.rag.ingestion.build_sparse_vector",
        lambda text: dummy_sparse,
    )
    emb_client = MagicMock()
    emb_client.embed.side_effect = lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts]
    emb_client.embed_one.return_value = [0.1, 0.2, 0.3, 0.4]
    monkeypatch.setattr(rag_module, "build_embedding_client", lambda: emb_client)
    # 配置齐全性校验（fastembed 可用性 + embedding 配置）单测中跳过，聚焦入库幂等逻辑
    monkeypatch.setattr(rag_module, "_ensure_ingest_ready", lambda: None)

    monkeypatch.setattr(rag_module, "get_knowledge_file_dao", lambda: dao)
    monkeypatch.setattr(rag_module, "get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr(
        rag_module, "get_rag_config_service", lambda: SimpleNamespace(get_config=_fake_config)
    )
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
    asyncio.run(env.dao.delete(rec["id"]))  # 软删除改写为哨兵 DELETED:{id}，释放真实哈希槽位

    # 删除后可重新上传相同内容（不会因唯一约束冲突）
    result = asyncio.run(rag_module.knowledge_upload(_make_request(), _make_file("d.md", content), "faq"))
    assert result["duplicated"] is False
    assert result["id"] != rec["id"]
    assert env.qdrant.upsert.call_count == 1


def test_update_knowledge_file_rebuilds_vectors(env):
    content = "# 原文档\n\n初版内容。"
    rec = asyncio.run(
        env.dao.create(
            1, "orig.md", len(content), "faq",
            status=KNOWLEDGE_FILE_STATUS_SUCCESS, content_hash=_hash(1, content),
        )
    )
    env.qdrant.reset_mock()
    new_content = "# 新文档\n\n改版内容。"
    new_hash = _hash(1, new_content)

    # 更新同 file_id：删旧向量 + 重建 + 刷新上传时间，doc_id 不变
    result = asyncio.run(
        rag_module.update_knowledge_file(
            rec["id"], _make_request(), _make_file("orig.md", new_content), "faq"
        )
    )
    assert result["id"] == rec["id"]            # 同一文件，doc_id 不变
    assert result["content_hash"] == new_hash   # 内容变更同步哈希
    assert result["duplicated"] is False
    # 旧向量删除 + 新向量写入各一次
    env.qdrant.delete_by_doc_id.assert_called_once_with(rec["id"])
    assert env.qdrant.upsert.call_count == 1


def test_upload_error_refreshes_created_at(env, monkeypatch):
    # 预置一条 ERROR 记录（模拟上次上传失败），重传同内容会复用并重新向量化
    content = "# 文档\n\n内容。"
    rec = asyncio.run(
        env.dao.create(
            1, "e.md", len(content), "faq",
            status=KNOWLEDGE_FILE_STATUS_ERROR, content_hash=_hash(1, content),
        )
    )
    old_created = env.dao._by_id[rec["id"]]["created_at"]
    # 强制向量化阶段抛错，触发错误分支
    fake_ingestion = MagicMock()
    fake_ingestion.embedding_client = None
    fake_ingestion.ingest_text.side_effect = RuntimeError("向量化失败")
    monkeypatch.setattr(rag_module, "_build_ingestion_service", lambda: fake_ingestion)

    with pytest.raises(Exception):
        asyncio.run(
            rag_module.knowledge_upload(_make_request(), _make_file("e.md", content), "faq")
        )

    row = env.dao._by_id[rec["id"]]
    # 错误分支刷新了 created_at（使失败上传按最新时间排序），状态回到 ERROR
    assert row["created_at"] >= old_created
    assert row["status"] == KNOWLEDGE_FILE_STATUS_ERROR
    assert row["error_message"] == "向量化失败"


def test_update_knowledge_file_duplicate_content_409(env):
    # 已存在文件 b（内容 B）
    content_b = "# 文件B\n\n已有内容。"
    asyncio.run(
        env.dao.create(
            1, "b.md", len(content_b), "faq",
            status=KNOWLEDGE_FILE_STATUS_SUCCESS, content_hash=_hash(1, content_b),
        )
    )
    # 文件 a 尝试更新成与 b 相同的内容 → 409
    content_a = "# 文件A\n\n初版。"
    rec_a = asyncio.run(
        env.dao.create(
            1, "a.md", len(content_a), "faq",
            status=KNOWLEDGE_FILE_STATUS_SUCCESS, content_hash=_hash(1, content_a),
        )
    )
    with pytest.raises(Exception) as exc:
        asyncio.run(
            rag_module.update_knowledge_file(
                rec_a["id"], _make_request(), _make_file("a.md", content_b), "faq"
            )
        )
    assert exc.value.status_code == 409


class TestIngestReady:
    """`_ensure_ingest_ready`：入库前统一校验 fastembed + embedding 双依赖齐全。"""

    def test_ok_when_both_ready(self, monkeypatch):
        monkeypatch.setattr(rag_module, "build_embedding_client", lambda: MagicMock())
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        # fastembed 可用 + embedding 已配置 → 不抛
        rag_module._ensure_ingest_ready()

    def test_missing_embedding_raises(self, monkeypatch):
        monkeypatch.setattr(rag_module, "build_embedding_client", lambda: None)
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        with pytest.raises(HTTPException) as exc:
            rag_module._ensure_ingest_ready()
        assert exc.value.status_code == 400

    def test_missing_fastembed_raises(self, monkeypatch):
        monkeypatch.setattr(rag_module, "build_embedding_client", lambda: MagicMock())
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        with pytest.raises(HTTPException) as exc:
            rag_module._ensure_ingest_ready()
        assert exc.value.status_code == 400

