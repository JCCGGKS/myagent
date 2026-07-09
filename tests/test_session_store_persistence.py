from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.dao import MemorySessionStore, SqlSessionStore
from app.model import Base, session as _session_models  # noqa: F401 (注册表)


def make_sql_store():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return SqlSessionStore(Session)


def _seed(store, user_id=1):
    sid = store.create_session(user_id, "web", "会话A")
    store.append_message(sid, "user", "你好")
    store.append_message(sid, "assistant", "请问有什么可以帮您")
    return sid


def test_sql_list_sessions_returns_seeded_session():
    store = make_sql_store()
    sid = _seed(store, 1)
    listed = store.list_sessions(1)
    assert len(listed) == 1
    assert listed[0]["session_id"] == sid
    assert listed[0]["title"] == "会话A"
    assert listed[0]["preview"] == "请问有什么可以帮您"


def test_sql_list_sessions_filters_by_user():
    store = make_sql_store()
    _seed(store, 1)
    _seed(store, 2)
    assert len(store.list_sessions(1)) == 1
    assert len(store.list_sessions(2)) == 1
    assert len(store.list_sessions(999)) == 0


def test_sql_get_messages_ordered():
    store = make_sql_store()
    sid = _seed(store, 1)
    msgs = store.get_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "你好"


def test_sql_update_title():
    store = make_sql_store()
    sid = _seed(store, 1)
    store.update_title(sid, "改名后")
    assert store.list_sessions(1)[0]["title"] == "改名后"


def test_sql_delete_session():
    store = make_sql_store()
    sid = _seed(store, 1)
    store.delete_session(sid)
    # 软删除：从列表隐藏，但会话与消息数据保留（可回放）。
    assert store.list_sessions(1) == []
    assert len(store.get_messages(sid)) == 2


def test_memory_list_and_messages():
    store = MemorySessionStore()
    sid = _seed(store, 1)
    listed = store.list_sessions(1)
    assert listed[0]["session_id"] == sid
    assert listed[0]["preview"] == "请问有什么可以帮您"
    msgs = store.get_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_memory_update_and_delete():
    store = MemorySessionStore()
    sid = _seed(store, 1)
    store.update_title(sid, "新名")
    assert store.list_sessions(1)[0]["title"] == "新名"
    store.delete_session(sid)
    assert store.list_sessions(1) == []
