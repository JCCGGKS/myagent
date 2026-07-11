"""测试 CustomerServiceAgent（RAG 工具化改造后）。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.business.agent import CustomerServiceAgent
from app.schema import ChatRequest, ConversationState
from app.dao import SessionStore


@pytest.fixture
def agent():
    """创建一个测试用的 CustomerServiceAgent 实例。"""
    store = AsyncMock()  # 会话服务为异步，使用 AsyncMock（子方法默认即异步）
    order_service = MagicMock()
    logistics_service = MagicMock()
    handoff_service = MagicMock()
    llm_client = AsyncMock()  # 异步 LLM 客户端
    message = MagicMock(content="这是 LLM 生成的回复。", tool_calls=None)
    llm_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=message)]
    )
    return CustomerServiceAgent(
        store=store,
        order_service=order_service,
        logistics_service=logistics_service,
        handoff_service=handoff_service,
        llm_client=llm_client,
        llm_model="fake-model",
    )


class TestCustomerServiceAgent:
    """测试 CustomerServiceAgent 的核心功能。"""

    def test_chat_should_route_to_agent_node(self, agent):
        """测试意图为 order_query 时，路由到 agent_node。"""
        request = ChatRequest(
            session_id="test-session",
            message="帮我查一下订单 A1001",
        )
        # 初始化 state 必填字段
        from app.schema import ConversationState

        state = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
        )
        state.intent_clarification_count = 0
        state.slot_clarification_count = 0
        agent.store.get.return_value = state

        response = asyncio.run(agent.chat(request, user_id=1))
        assert response.main_intent == "order_query"
        # 后续接入真实 LLM 后，断言会调用 agent_node

    def test_chat_should_route_to_response_generator(self, agent):
        """测试非业务消息（如问候）无法识别意图时，路由到 response_generator 进行澄清。"""
        request = ChatRequest(
            session_id="test-session",
            message="你好",
        )
        # 初始化 state 必填字段
        from app.schema import ConversationState

        state = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
        )
        state.intent_clarification_count = 0
        state.slot_clarification_count = 0
        agent.store.get.return_value = state

        response = asyncio.run(agent.chat(request, user_id=1))
        assert response.main_intent == "unrecognize"

    def test_agent_node_should_call_tools(self, agent):
        """测试 agent_node 能够调用工具（如 rag_retrieve）。"""
        # TODO: 接入真实 LLM 后，断言会调用 rag_retrieve 工具
        pass

    def test_response_generator_should_use_llm(self, agent):
        """测试 response_generator 使用 LLM 生成响应（非模板）。"""
        # TODO: 接入真实 LLM 后，断言响应是 LLM 生成的
        pass
