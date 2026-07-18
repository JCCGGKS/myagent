from __future__ import annotations

from app.dao.knowledge_file import (
    KnowledgeFileDAO,
    MemoryKnowledgeFileDAO,
    SqlKnowledgeFileDAO,
)
from app.dao.session import MemorySessionStore, SessionStore, SqlSessionStore
from app.dao.user import MemoryUserDAO, SqlUserDAO, UserDAO
from app.dao.event_log import (
    EventLogStore,
    MemoryEventLogStore,
    SqlEventLogStore,
    get_event_log_store,
)
from app.model import AsyncSessionLocal


def get_session_store() -> SessionStore:
    """根据是否配置 mysql（异步 engine 可用）选择实现：有异步 engine 用 Sql，否则内存。

    M2 起 SqlSessionStore 使用 AsyncSession；注入 AsyncSessionLocal（原生异步）。
    异步 engine 不可用时回退到内存实现（进程内状态，适合本地/测试）。
    """
    if AsyncSessionLocal is not None:
        return SqlSessionStore(AsyncSessionLocal)
    return MemorySessionStore()


def get_user_dao() -> UserDAO:
    """根据是否配置 mysql（异步 engine 可用）选择实现：有异步 engine 用 Sql，否则内存。"""
    if AsyncSessionLocal is not None:
        return SqlUserDAO(AsyncSessionLocal)
    return MemoryUserDAO()


def get_knowledge_file_dao() -> KnowledgeFileDAO:
    """根据是否配置 mysql（异步 engine 可用）选择实现：有异步 engine 用 Sql，否则内存。"""
    if AsyncSessionLocal is not None:
        return SqlKnowledgeFileDAO(AsyncSessionLocal)
    return MemoryKnowledgeFileDAO()


__all__ = [
    "SessionStore",
    "MemorySessionStore",
    "SqlSessionStore",
    "EventLogStore",
    "MemoryEventLogStore",
    "SqlEventLogStore",
    "get_event_log_store",
    "UserDAO",
    "MemoryUserDAO",
    "SqlUserDAO",
    "get_session_store",
    "get_user_dao",
    "KnowledgeFileDAO",
    "MemoryKnowledgeFileDAO",
    "SqlKnowledgeFileDAO",
    "get_knowledge_file_dao",
]
