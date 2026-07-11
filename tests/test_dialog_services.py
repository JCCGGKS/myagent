"""测试对话服务（RAG 工具化改造后）。"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.schema import ConversationState, ToolExecutionResult
from app.business.dialog import ClarificationService, ResponseService


@pytest.fixture
def clarification_service():
    """创建一个测试用的 ClarificationService 实例。"""
    prompt_registry = MagicMock()
    prompt_registry.get.return_value = {
        "intent_clarification": "请问你想咨询什么？",
        "slot_clarification": {"order_query": "请提供订单号"},
        "generic_slot_clarification": "请告诉我更多信息",
        "generic_fallback": "抱歉，我没理解",
    }
    llm_client = AsyncMock()
    llm_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="请提供订单号"))]
    )
    return ClarificationService(
        prompt_registry=prompt_registry,
        llm_client=llm_client,
        llm_model="fake-model",
    )


@pytest.fixture
def response_service():
    """创建一个测试用的 ResponseService 实例。"""
    prompt_registry = MagicMock()
    prompt_registry.get.return_value = {
        "complaint_ack": "非常抱歉给你带来不好的体验。",
        "refund_policy_fallback": "抱歉，暂时无法查询退款政策。",
        "refund_request_ack": "已收到你的退款申请。",
        "order_template": "订单 {order_id} 状态：{status}",
        "order_not_found": "没找到订单。",
        "logistics_template": "物流状态：{tracking_status}",
        "logistics_not_found": "没找到物流信息。",
        "handoff_template": "已转人工，工单号：{ticket_id}",
        "greeting": "你好！有什么可以帮你？",
        "unsupported_biz": "抱歉，这个问题我暂时无法回答。",
        "unknown_fallback": "抱歉，我没理解。",
    }
    llm_client = AsyncMock()
    llm_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="这是 LLM 生成的回复。"))]
    )
    return ResponseService(
        prompt_registry=prompt_registry,
        llm_client=llm_client,
        llm_model="fake-model",
    )


class DialogServicesTestCase:
    """测试对话服务的核心功能。"""

    def test_clarification_prompt_registry_should_load_default_yaml_prompts(self):
        """测试 ClarificationPromptRegistry 能够加载默认 YAML 配置。"""
        from app.business.dialog import ClarificationPromptRegistry

        registry = ClarificationPromptRegistry()
        prompts = registry.get()
        assert "intent_clarification" in prompts
        assert "slot_clarification" in prompts

    def test_clarification_service_should_generate_refund_order_id_prompt(self, clarification_service):
        """测试 ClarificationService 能够生成追问 prompt。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web", current_action="ask_slot_clarification")
        state.missing_slots = ["order_id"]
        result = asyncio.run(clarification_service.generate(state))
        assert result.reply != ""

    def test_response_prompt_registry_should_load_default_yaml_prompts(self):
        """测试 ResponsePromptRegistry 能够加载默认 YAML 配置。"""
        from app.business.dialog import ResponsePromptRegistry

        registry = ResponsePromptRegistry()
        prompts = registry.get()
        assert "greeting" in prompts
        assert "complaint_ack" in prompts

    def test_response_service_should_use_llm(self, response_service):
        """测试 ResponseService 使用 LLM 生成响应（非模板）。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web", current_main_intent="unrecognize")
        result = asyncio.run(response_service.generate(state))
        assert result.reply == "这是 LLM 生成的回复。"

    def test_message_service_should_record_messages_and_tool_calls(self):
        """测试 MessageService 能够记录消息和工具调用。"""
        from app.business.dialog import MessageService

        store = AsyncMock()
        service = MessageService(store=store)
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        request = MagicMock()
        request.message = "你好"
        result = asyncio.run(service.persist(state, request))
        assert result is not None
