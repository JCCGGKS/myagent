from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.dao import MemoryKnowledgeFileDAO, SqlKnowledgeFileDAO
from app.model import Base, knowledge as _knowledge_models  # noqa: F401 (注册表)
from app.model.knowledge import (
    KNOWLEDGE_FILE_STATUS_ERROR,
    KNOWLEDGE_FILE_STATUS_PROCESSING,
    KNOWLEDGE_FILE_STATUS_SUCCESS,
)


def make_sql_dao():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return SqlKnowledgeFileDAO(Session)


def _scenarios():
    yield MemoryKnowledgeFileDAO()
    yield make_sql_dao()


def test_create_and_get():
    for dao in _scenarios():
        rec = dao.create(1, "a.md", 1024, "markdown", status=KNOWLEDGE_FILE_STATUS_PROCESSING)
        assert rec["id"]
        assert rec["status"] == KNOWLEDGE_FILE_STATUS_PROCESSING
        got = dao.get_by_id(rec["id"])
        assert got["filename"] == "a.md"
        assert got["file_size"] == 1024


def test_update_status():
    for dao in _scenarios():
        rec = dao.create(1, "a.md", 1024, "markdown")
        dao.update_status(rec["id"], KNOWLEDGE_FILE_STATUS_SUCCESS, chunk_count=7)
        got = dao.get_by_id(rec["id"])
        assert got["status"] == KNOWLEDGE_FILE_STATUS_SUCCESS
        assert got["chunk_count"] == 7

        dao.update_status(rec["id"], KNOWLEDGE_FILE_STATUS_ERROR, error_message="boom")
        got = dao.get_by_id(rec["id"])
        assert got["status"] == KNOWLEDGE_FILE_STATUS_ERROR
        assert got["error_message"] == "boom"


def test_list_by_user_filters_others_and_deleted():
    for dao in _scenarios():
        r1 = dao.create(1, "a.md", 10, "markdown")
        r2 = dao.create(1, "b.json", 20, "json")
        dao.create(2, "c.md", 30, "markdown")  # 其他用户

        items = dao.list_by_user(1)
        ids = {i["id"] for i in items}
        assert {r1["id"], r2["id"]} <= ids
        assert all(i["user_id"] == 1 for i in items)

        # 软删除 r1 后从列表消失
        dao.delete(r1["id"])
        assert dao.get_by_id(r1["id"]) is None
        assert all(i["id"] != r1["id"] for i in dao.list_by_user(1))


def test_list_ordered_desc():
    for dao in _scenarios():
        r1 = dao.create(1, "a.md", 10, "markdown")
        r2 = dao.create(1, "b.md", 10, "markdown")
        ids = [i["id"] for i in dao.list_by_user(1)]
        assert ids == [r2["id"], r1["id"]]
