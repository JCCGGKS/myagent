from __future__ import annotations

import asyncio

from app.dao import MemorySessionStore, SqlSessionStore
from app.model import session as _session_models  # noqa: F401 (注册表)
from conftest import make_async_session_factory


def make_sql_store() -> SqlSessionStore:
    """M2：SqlSessionStore 使用 AsyncSession，注入异步会话工厂。"""
    return SqlSessionStore(make_async_session_factory())


async def _seed(store: Any, user_id: int = 1) -> str:
    sid = await store.create_session(user_id, "web", "会话A")
    await store.append_message(sid, "user", "你好")
    await store.append_message(sid, "assistant", "请问有什么可以帮您")
    return sid


def test_sql_list_sessions_returns_seeded_session():
    store = make_sql_store()
    sid = asyncio.run(_seed(store, 1))
    listed = asyncio.run(store.list_sessions(1))
    assert len(listed) == 1
    assert listed[0]["session_id"] == sid
    assert listed[0]["title"] == "会话A"


def test_sql_list_sessions_filters_by_user():
    store = make_sql_store()
    asyncio.run(_seed(store, 1))
    asyncio.run(_seed(store, 2))
    assert len(asyncio.run(store.list_sessions(1))) == 1
    assert len(asyncio.run(store.list_sessions(2))) == 1
    assert len(asyncio.run(store.list_sessions(999))) == 0


def test_sql_get_messages_ordered():
    store = make_sql_store()
    sid = asyncio.run(_seed(store, 1))
    msgs = asyncio.run(store.get_messages(sid))
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "你好"


def test_sql_update_title():
    store = make_sql_store()
    sid = asyncio.run(_seed(store, 1))
    asyncio.run(store.update_title(sid, "改名后"))
    assert asyncio.run(store.list_sessions(1))[0]["title"] == "改名后"


def test_sql_delete_session():
    store = make_sql_store()
    sid = asyncio.run(_seed(store, 1))
    asyncio.run(store.delete_session(sid))
    # 软删除：从列表隐藏，但会话与消息数据保留（可回放）。
    assert asyncio.run(store.list_sessions(1)) == []
    assert len(asyncio.run(store.get_messages(sid))) == 2


def test_memory_list_and_messages():
    store = MemorySessionStore()
    sid = asyncio.run(_seed(store, 1))
    listed = asyncio.run(store.list_sessions(1))
    assert listed[0]["session_id"] == sid
    msgs = asyncio.run(store.get_messages(sid))
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    # 回放消息必须带 id，否则前端 v-for :key 失效导致刷新后消息“消失”
    assert all("id" in m and m["id"] for m in msgs)


def test_sql_get_messages_includes_id():
    store = make_sql_store()
    sid = asyncio.run(_seed(store, 1))
    msgs = asyncio.run(store.get_messages(sid))
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert all("id" in m and m["id"] for m in msgs)


def test_memory_update_and_delete():
    store = MemorySessionStore()
    sid = asyncio.run(_seed(store, 1))
    asyncio.run(store.update_title(sid, "新名"))
    assert asyncio.run(store.list_sessions(1))[0]["title"] == "新名"
    asyncio.run(store.delete_session(sid))
    assert asyncio.run(store.list_sessions(1)) == []


def test_memory_ensure_session_registers_owner_without_persist():
    # 聊天失败未落库时，ensure_session 仍需登记归属，否则后续管理接口会 404。
    store = MemorySessionStore()
    sid = "sess-no-persist"
    asyncio.run(store.ensure_session(sid, user_id=1, channel="web"))
    assert asyncio.run(store.get_user_id(sid)) == 1
    assert asyncio.run(store.list_sessions(1))[0]["session_id"] == sid
    # 已存在则不覆盖归属
    asyncio.run(store.ensure_session(sid, user_id=2, channel="web"))
    assert asyncio.run(store.get_user_id(sid)) == 1


def test_sql_ensure_session_registers_owner_without_persist():
    store = make_sql_store()
    sid = "sess-no-persist"
    asyncio.run(store.ensure_session(sid, user_id=1, channel="web"))
    assert asyncio.run(store.get_user_id(sid)) == 1
    assert asyncio.run(store.list_sessions(1))[0]["session_id"] == sid
    asyncio.run(store.ensure_session(sid, user_id=2, channel="web"))
    assert asyncio.run(store.get_user_id(sid)) == 1


def test_rename_before_chat_succeeds():
    # 回归：前端建会话后、未发任何消息就改名，后端不能 404。
    from app.business.dialog import SessionService

    service = SessionService(MemorySessionStore())
    sid = "sess-rename-first"
    asyncio.run(service.ensure_session(sid, user_id=1))
    asyncio.run(service.rename(sid, "先命名"))
    listed = asyncio.run(service.list_sessions(1))
    assert listed[0]["session_id"] == sid
    assert listed[0]["title"] == "先命名"
