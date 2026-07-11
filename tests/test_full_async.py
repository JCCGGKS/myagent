"""验证全异步链路（M1/M2）：call_llm_async、graph.astream 异步事件、chat/chat_events 协程、
以及 M2 原生异步 DAO（AsyncSession）的真实往返。

不依赖真实 LLM/MySQL：业务协程用 AsyncMock 驱动，DAO 用内存 aiosqlite 驱动；
重点验证：
- 业务方法现在为协程（await 调用）
- chat_events 是异步生成器并按节点产出事件
- chat 返回结构化 ChatResponse
- M2：UserDAO / KnowledgeFileDAO / SessionStore 均基于 AsyncSession，可 await 且真实落库
详见 plans/full-async-plan.md。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.business.agent import CustomerServiceAgent
from app.business.dialog import MessageService, SessionService
from app.dao import (
    MemorySessionStore,
    SqlKnowledgeFileDAO,
    SqlSessionStore,
    SqlUserDAO,
)
from app.schema import ChatRequest, ConversationState
from app.utils.llm import call_llm_async
from conftest import make_async_session_factory


def _async_factory():
    return make_async_session_factory()


def _make_llm_mock(content: str, tool_calls=None):
    llm_client = AsyncMock()
    message = MagicMock(content=content, tool_calls=tool_calls)
    llm_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=message)]
    )
    return llm_client


def _make_agent():
    order_service = MagicMock()
    logistics_service = MagicMock()
    handoff_service = MagicMock()
    llm_client = _make_llm_mock("这是助手回复。")
    agent = CustomerServiceAgent(
        store=AsyncMock(),
        order_service=order_service,
        logistics_service=logistics_service,
        handoff_service=handoff_service,
        llm_client=llm_client,
        llm_model="fake-model",
    )
    # 跳过 LLM 兜底分类（保持同步内存路由即可）
    agent.intent_router_service.llm_fallback_service = None
    # 让 _build_payload 走「无历史 -> 新建 ConversationState」分支（AsyncMock 默认返回 MagicMock）
    agent.store.get.return_value = None
    return agent


def test_call_llm_async_returns_parsed_content():
    async def _run():
        llm_client = _make_llm_mock("你好，有什么可以帮你？")
        result = await call_llm_async(llm_client, "fake-model", [{"role": "user", "content": "hi"}])
        return result

    result = asyncio.run(_run())
    assert result["content"] == "你好，有什么可以帮你？"
    assert result["tool_calls"] == []


def test_call_llm_async_parses_tool_calls():
    async def _run():
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "rag_retrieve"
        tc.function.arguments = '{"query": "x"}'
        llm_client = _make_llm_mock("ignored", tool_calls=[tc])
        result = await call_llm_async(llm_client, "fake-model", [], tools=[{"name": "rag_retrieve"}])
        return result

    result = asyncio.run(_run())
    assert result["tool_calls"][0]["function"]["name"] == "rag_retrieve"


def test_chat_returns_response_via_async():
    agent = _make_agent()
    request = ChatRequest(session_id="s1", message="你好")
    response = asyncio.run(agent.chat(request, user_id=1))
    assert response.reply == "这是助手回复。"
    # 回传 session_id，使前端能按会话 id 将回复渲染到对应聊天框
    assert response.session_id == "s1"
    # 精简后的 session_state 仅含 StatsPanel 消费的字段（含多意图 pending_intents）
    assert set(response.session_state.keys()) == {
        "current_main_intent",
        "current_sub_intent",
        "stage",
        "slots",
        "missing_slots",
        "needs_clarification",
        "summary",
        "pending_intents",
    }


def test_chat_events_is_async_generator_and_emits_events():
    agent = _make_agent()
    # 用订单查询触发 agent_node -> response_generator（产出 final 事件）
    request = ChatRequest(session_id="s1", message="帮我查一下订单 A1001")

    async def _collect():
        types = []
        async for ev in agent.chat_events(request, user_id=1):
            types.append(ev.get("type"))
        return types

    types = asyncio.run(_collect())
    # 至少包含意图识别与最终回复两类事件
    assert "intent" in types
    assert "final" in types


def test_chat_events_persists_before_final():
    """先落库（用户消息尽早、助手回复在 final 前）再下发 final。

    用户消息在请求一开始就落库，助手回复在 final 之前落库；
    即使处理中刷新页面，用户刚发送的内容也不会丢失。
    """
    agent = _make_agent()
    order: list[str] = []

    async def _persist_user(state, request):
        order.append("persist_user")
        return None

    async def _persist_assistant(state, request):
        order.append("persist_assistant")
        return None

    agent.message_service.persist_user_message = _persist_user
    agent.message_service.persist_assistant_reply = _persist_assistant

    request = ChatRequest(session_id="s1", message="帮我查一下订单 A1001")

    async def _collect():
        async for ev in agent.chat_events(request, user_id=1):
            if ev.get("type") == "final":
                order.append("final")

    asyncio.run(_collect())
    assert {"persist_user", "persist_assistant", "final"} <= set(order)
    assert order.index("persist_user") < order.index("final")
    assert order.index("persist_assistant") < order.index("final")


def test_user_message_persisted_before_processing():
    """回归：用户消息在图运行前就落库，处理中被打断（如刷新页面）也不丢消息。"""
    from app.dao import MemorySessionStore

    store = MemorySessionStore()
    agent = _make_agent()
    agent.store = store
    # 让 message_service 使用真实 store
    agent.message_service.store = store

    request = ChatRequest(session_id="s1", message="帮我查一下订单 A1001")

    async def _run():
        # 模拟「请求刚开始就中断」：在图产出首个事件后立即停止消费，
        # 但此时用户消息应已早早落库。
        gen = agent.chat_events(request, user_id=1)
        await gen.__anext__()  # 消费一个事件（intent）后中断
        # 不 close 也会触发生成器回收；这里显式确认 store 中已有用户消息

    asyncio.run(_run())

    messages = asyncio.run(store.get_messages("s1"))
    roles = [m["role"] for m in messages]
    assert "user" in roles, f"用户消息未落库，实际消息: {messages}"
    assert any(m["role"] == "user" and m["content"] == request.message for m in messages)


def test_message_service_persist_is_async():
    store = AsyncMock()
    service = MessageService(store=store)
    state = ConversationState(session_id="s1", user_id=1, channel="web")
    state.reply = "回复"
    request = MagicMock()
    request.message = "你好"

    result = asyncio.run(service.persist(state, request))
    assert result is state
    # 两次 append_message（user/assistant）+ 一次 save 都被 await 调用
    assert store.append_message.await_count == 2
    assert store.save.await_count == 1


def test_m2_user_dao_async_roundtrip():
    """M2：SqlUserDAO 基于 AsyncSession，可 await 且真实落库。"""
    dao = SqlUserDAO(_async_factory())

    async def _run():
        created = await dao.create("alice", "a@x.com", "hash")
        by_name = await dao.get_by_username("alice")
        by_id = await dao.get_by_id(created["id"])
        await dao.update_password(created["id"], "newhash")
        by_name2 = await dao.get_by_username("alice")
        return created, by_name, by_id, by_name2

    created, by_name, by_id, by_name2 = asyncio.run(_run())
    assert created["id"] == by_name["id"] == by_id["id"]
    assert by_name["email"] == "a@x.com"
    assert by_name2["password_hash"] == "newhash"


def test_m2_knowledge_file_dao_async_roundtrip():
    """M2：SqlKnowledgeFileDAO 基于 AsyncSession，可 await 且真实落库。"""
    dao = SqlKnowledgeFileDAO(_async_factory())

    async def _run():
        rec = await dao.create(1, "a.md", 10, "markdown", status=1)
        got = await dao.get_by_id(rec["id"])
        await dao.update_status(rec["id"], 2, chunk_count=5)
        updated = await dao.get_by_id(rec["id"])
        listed = await dao.list_by_user(1)
        await dao.delete(rec["id"])
        after_delete = await dao.get_by_id(rec["id"])
        return got, updated, listed, after_delete

    got, updated, listed, after_delete = asyncio.run(_run())
    assert got["filename"] == "a.md"
    assert updated["status"] == 2 and updated["chunk_count"] == 5
    assert listed[0]["id"] == got["id"]
    assert after_delete is None


def test_m2_session_store_async_via_service():
    """M2：SqlSessionStore（AsyncSession）经 SessionService 走真实 await 往返。"""
    service = SessionService(SqlSessionStore(_async_factory()))

    async def _run():
        await service.ensure_session("s1", user_id=7)
        await service.append_message("s1", "user", "你好")
        await service.append_message("s1", "assistant", "在的")
        await service.rename("s1", "会话一")
        sessions = await service.list_sessions(7)
        messages = await service.get_messages("s1")
        owner = await service.get_owner("s1")
        return sessions, messages, owner

    sessions, messages, owner = asyncio.run(_run())
    assert sessions[0]["session_id"] == "s1"
    assert sessions[0]["title"] == "会话一"
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert owner == 7


def test_m2_memory_stores_remain_async():
    """内存实现在 M2 同样为 async，接口与 SQL 实现一致（可直接 await）。"""
    store = MemorySessionStore()

    async def _run():
        await store.ensure_session("m1", user_id=3)
        await store.append_message("m1", "user", "hi")
        return await store.get_user_id("m1")

    assert asyncio.run(_run()) == 3
