"""测试公共夹具：异步 SQLite 会话工厂 + 测试后统一 dispose。

M2 起 DAO 测试使用 ``aiosqlite`` 异步引擎；若不在事件循环关闭前 dispose，
aiosqlite 的 worker 线程会在已关闭的 loop 上调度回调，触发
``PytestUnhandledThreadExceptionWarning``（仅测试噪音，生产环境事件循环常驻不会触发）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.model import Base

_ENGINES: list[Any] = []


def make_async_session_factory() -> Any:
    """构造内存 SQLite 的异步会话工厂（StaticPool 保证单连接、表结构跨连接可见）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_bootstrap(engine))
    _ENGINES.append(engine)
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def _bootstrap(engine: Any) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
def _dispose_async_engines():
    yield
    # 测试结束后统一 dispose 异步 engine，回收 aiosqlite worker 线程。
    for engine in _ENGINES:
        asyncio.run(engine.dispose())
    _ENGINES.clear()
