from __future__ import annotations

import asyncio

from app.dao import MemoryKnowledgeFileDAO, SqlKnowledgeFileDAO
from app.dao.knowledge_file import DuplicateKnowledgeFileError
from app.model import knowledge as _knowledge_models  # noqa: F401 (注册表)
from app.model.knowledge import (
    KNOWLEDGE_FILE_STATUS_ERROR,
    KNOWLEDGE_FILE_STATUS_PROCESSING,
    KNOWLEDGE_FILE_STATUS_SUCCESS,
)
from conftest import make_async_session_factory


def make_sql_dao() -> SqlKnowledgeFileDAO:
    """M2：SqlKnowledgeFileDAO 使用 AsyncSession，注入异步会话工厂。"""
    return SqlKnowledgeFileDAO(make_async_session_factory())


def _scenarios():
    yield MemoryKnowledgeFileDAO()
    yield make_sql_dao()


def test_create_and_get():
    for dao in _scenarios():
        rec = asyncio.run(
            dao.create(1, "a.md", 1024, "markdown", status=KNOWLEDGE_FILE_STATUS_PROCESSING)
        )
        assert rec["id"]
        assert rec["status"] == KNOWLEDGE_FILE_STATUS_PROCESSING
        got = asyncio.run(dao.get_by_id(rec["id"]))
        assert got["filename"] == "a.md"
        assert got["file_size"] == 1024


def test_update_status():
    for dao in _scenarios():
        rec = asyncio.run(dao.create(1, "a.md", 1024, "markdown"))
        asyncio.run(
            dao.update_status(rec["id"], KNOWLEDGE_FILE_STATUS_SUCCESS, chunk_count=7)
        )
        got = asyncio.run(dao.get_by_id(rec["id"]))
        assert got["status"] == KNOWLEDGE_FILE_STATUS_SUCCESS
        assert got["chunk_count"] == 7

        asyncio.run(
            dao.update_status(rec["id"], KNOWLEDGE_FILE_STATUS_ERROR, error_message="boom")
        )
        got = asyncio.run(dao.get_by_id(rec["id"]))
        assert got["status"] == KNOWLEDGE_FILE_STATUS_ERROR
        assert got["error_message"] == "boom"


def test_list_by_user_filters_others_and_deleted():
    for dao in _scenarios():
        r1 = asyncio.run(dao.create(1, "a.md", 10, "markdown", content_hash="h_r1"))
        r2 = asyncio.run(dao.create(1, "b.json", 20, "json", content_hash="h_r2"))
        asyncio.run(dao.create(2, "c.md", 30, "markdown", content_hash="h_c"))  # 其他用户

        items = asyncio.run(dao.list_by_user(1))
        ids = {i["id"] for i in items}
        assert {r1["id"], r2["id"]} <= ids
        assert all(i["user_id"] == 1 for i in items)

        # 软删除 r1 后从列表消失
        asyncio.run(dao.delete(r1["id"]))
        assert asyncio.run(dao.get_by_id(r1["id"])) is None
        assert all(i["id"] != r1["id"] for i in asyncio.run(dao.list_by_user(1)))


def test_list_ordered_desc():
    for dao in _scenarios():
        r1 = asyncio.run(dao.create(1, "a.md", 10, "markdown", content_hash="h_r1"))
        r2 = asyncio.run(dao.create(1, "b.md", 10, "markdown", content_hash="h_r2"))
        ids = [i["id"] for i in asyncio.run(dao.list_by_user(1))]
        assert ids == [r2["id"], r1["id"]]


def test_create_stores_content_hash():
    for dao in _scenarios():
        rec = asyncio.run(dao.create(1, "a.md", 10, "markdown", content_hash="h1"))
        assert rec["content_hash"] == "h1"
        got = asyncio.run(dao.get_by_id(rec["id"]))
        assert got["content_hash"] == "h1"


def test_find_by_content_hash_returns_latest_after_delete():
    for dao in _scenarios():
        first = asyncio.run(
            dao.create(1, "a.md", 10, "markdown", content_hash="dup", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        # 删除后哈希被改写为哨兵 DELETED:{id}（非 NULL、按主键唯一），释放真实哈希槽位
        asyncio.run(dao.delete(first["id"]))
        second = asyncio.run(
            dao.create(1, "a-renamed.md", 10, "markdown", content_hash="dup", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        found = asyncio.run(dao.find_by_content_hash(1, "dup"))
        assert found is not None
        assert found["id"] == second["id"]
        assert found["filename"] == "a-renamed.md"


def test_delete_writes_sentinel_not_null():
    for dao in _scenarios():
        rec = asyncio.run(
            dao.create(1, "a.md", 10, "markdown", content_hash="dup", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        asyncio.run(dao.delete(rec["id"]))
        # 软删后按 deleted_at 过滤：列表/查重看不到原记录，但也不写 NULL
        assert asyncio.run(dao.get_by_id(rec["id"])) is None
        assert asyncio.run(dao.find_by_content_hash(1, "dup")) is None
        # 删除后重传同内容：槽位已释放，自然新建一条（证明哨兵非 NULL 且未占用真实哈希）
        second = asyncio.run(
            dao.create(1, "a-renamed.md", 10, "markdown", content_hash="dup", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        assert second["id"] != rec["id"]


def test_delete_multiple_files_no_unique_conflict():
    for dao in _scenarios():
        # 同一用户删除多个不同文件：哨兵 DELETED:{id} 各自唯一，
        # 不会因哨兵重复而撞 (user_id, content_hash) 唯一约束（否则第二次 delete 会抛错）
        a = asyncio.run(dao.create(1, "a.md", 10, "markdown", content_hash="ha"))
        b = asyncio.run(dao.create(1, "b.md", 10, "markdown", content_hash="hb"))
        asyncio.run(dao.delete(a["id"]))
        asyncio.run(dao.delete(b["id"]))  # 关键断言：不抛 DuplicateKnowledgeFileError
        # 删除后两条原内容均可重新上传（槽位各自释放）
        ra = asyncio.run(dao.create(1, "a2.md", 10, "markdown", content_hash="ha"))
        rb = asyncio.run(dao.create(1, "b2.md", 10, "markdown", content_hash="hb"))
        assert ra["id"] != a["id"]
        assert rb["id"] != b["id"]


def test_find_by_content_hash_ignores_deleted():
    for dao in _scenarios():
        rec = asyncio.run(
            dao.create(1, "a.md", 10, "markdown", content_hash="gone", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        asyncio.run(dao.delete(rec["id"]))
        assert asyncio.run(dao.find_by_content_hash(1, "gone")) is None


def test_find_by_content_hash_scoped_by_user():
    for dao in _scenarios():
        asyncio.run(
            dao.create(1, "a.md", 10, "markdown", content_hash="shared", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        # 不同用户同哈希不可见
        assert asyncio.run(dao.find_by_content_hash(2, "shared")) is None


def test_create_duplicate_content_hash_raises():
    for dao in _scenarios():
        asyncio.run(
            dao.create(1, "a.md", 10, "markdown", content_hash="dup", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
        )
        try:
            asyncio.run(
                dao.create(1, "b.md", 10, "markdown", content_hash="dup", status=KNOWLEDGE_FILE_STATUS_SUCCESS)
            )
            raise AssertionError("expected DuplicateKnowledgeFileError")
        except DuplicateKnowledgeFileError:
            pass
