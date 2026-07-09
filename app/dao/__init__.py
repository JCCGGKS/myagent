from __future__ import annotations

from app.dao.knowledge import KnowledgeStore
from app.dao.session import MemorySessionStore, SessionStore, SqlSessionStore
from app.dao.user import MemoryUserDAO, SqlUserDAO, UserDAO
from app.model import SessionLocal


def get_session_store() -> SessionStore:
    """根据是否配置 mysql 选择实现：有 engine 用 Sql，否则内存。"""
    if SessionLocal is not None:
        return SqlSessionStore(SessionLocal)
    return MemorySessionStore()


def get_user_dao() -> UserDAO:
    """根据是否配置 mysql 选择实现：有 engine 用 Sql，否则内存。"""
    if SessionLocal is not None:
        return SqlUserDAO(SessionLocal)
    return MemoryUserDAO()


__all__ = [
    "SessionStore",
    "MemorySessionStore",
    "SqlSessionStore",
    "UserDAO",
    "MemoryUserDAO",
    "SqlUserDAO",
    "get_session_store",
    "get_user_dao",
    "KnowledgeStore",
]
