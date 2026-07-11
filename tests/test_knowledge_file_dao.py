from __future__ import annotations

import asyncio

from app.dao import MemoryKnowledgeFileDAO, SqlKnowledgeFileDAO
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
        r1 = asyncio.run(dao.create(1, "a.md", 10, "markdown"))
        r2 = asyncio.run(dao.create(1, "b.json", 20, "json"))
        asyncio.run(dao.create(2, "c.md", 30, "markdown"))  # 其他用户

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
        r1 = asyncio.run(dao.create(1, "a.md", 10, "markdown"))
        r2 = asyncio.run(dao.create(1, "b.md", 10, "markdown"))
        ids = [i["id"] for i in asyncio.run(dao.list_by_user(1))]
        assert ids == [r2["id"], r1["id"]]
