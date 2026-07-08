"""测试路由服务（RAG 工具化改造后）。"""

import pytest
from unittest.mock import MagicMock, patch

from app.models import ConversationState, IntentResult
from app.services.routing import (
    HandoffClarificationPolicy,
    IntentRouterService,
    StateTrackerService,
)


@pytest.fixture
def router():
    """创建一个测试用的 IntentRouterService 实例。"""
    rule_registry = MagicMock()
    rule_registry.get.return_value = {
        "handoff_keywords": ["转人工", "人工客服"],
        "complaint_keywords": ["投诉", "抱怨"],
        "logistics_keywords": ["物流", "快递"],
        "order_query_keywords": ["订单", "下单"],
        "after_sale_refund_keywords": ["退款", "退货"],
        "after_sale_refund_action_keywords": ["申请退款", "办理退货"],
        "greeting_keywords": ["你好", "嗨"],
    }
    return IntentRouterService(rule_registry=rule_registry)


@pytest.fixture
def policy():
    """创建一个测试用的 HandoffClarificationPolicy 实例。"""
    return HandoffClarificationPolicy()


@pytest.fixture
def state_tracker():
    """创建一个测试用的 StateTrackerService 实例。"""
    schema_registry = MagicMock()
    schema_registry.get.return_value = {
        "required_slots": [],
        "optional_slots": [],
    }
    return StateTrackerService(schema_registry=schema_registry)


class RoutingServicesTestCase:
    """测试路由服务的核心功能。"""

    def test_intent_router_should_recognize_order_query(self, router):
        """测试能够识别订单查询意图。"""
        state = ConversationState(session_id="test-session")
        result = router.route(state, "帮我查一下订单 A1001")
        assert result.main_intent == "order_query"

    def test_intent_router_should_recognize_logistics(self, router):
        """测试能够识别物流查询意图。"""
        state = ConversationState(session_id="test-session")
        result = router.route(state, "我的快递到哪了")
        assert result.main_intent == "logistics"

    def test_intent_router_should_recognize_complaint(self, router):
        """测试能够识别投诉意图。"""
        state = ConversationState(session_id="test-session")
        result = router.route(state, "你们什么破平台，投诉")
        assert result.main_intent == "complaint"

    def test_intent_router_should_recognize_handoff(self, router):
        """测试能够识别转人工意图。"""
        state = ConversationState(session_id="test-session")
        result = router.route(state, "转人工")
        assert result.main_intent == "handoff_service"

    def test_intent_router_should_recognize_greeting(self, router):
        """测试能够识别问候意图。"""
        state = ConversationState(session_id="test-session")
        result = router.route(state, "你好")
        assert result.main_intent == "chitchat"

    def test_policy_should_set_agent_process_for_order_query(self, policy):
        """测试订单查询意图的 policy 决策（需要工具调用）。"""
        state = ConversationState(session_id="test-session", current_main_intent="order_query")
        result = policy.decide(state)
        assert result.current_action == "agent_process"

    def test_policy_should_set_agent_process_for_logistics(self, policy):
        """测试物流查询意图的 policy 决策（需要工具调用）。"""
        state = ConversationState(session_id="test-session", current_main_intent="logistics")
        result = policy.decide(state)
        assert result.current_action == "agent_process"

    def test_policy_should_set_agent_process_for_complaint(self, policy):
        """测试投诉意图的 policy 决策（需要工具调用）。"""
        state = ConversationState(session_id="test-session", current_main_intent="complaint")
        result = policy.decide(state)
        assert result.current_action == "agent_process"

    def test_policy_should_set_answer_directly_for_chitchat(self, policy):
        """测试问候意图的 policy 决策（不需要工具）。"""
        state = ConversationState(session_id="test-session", current_main_intent="chitchat")
        result = policy.decide(state)
        assert result.current_action == "answer_directly"

    def test_policy_should_set_answer_directly_for_unrecognize(self, policy):
        """测试未识别意图的 policy 决策（不需要工具）。"""
        state = ConversationState(session_id="test-session", current_main_intent="unrecognize")
        result = policy.decide(state)
        assert result.current_action == "answer_directly"

    def test_state_tracker_should_update_state(self, state_tracker):
        """测试状态跟踪器能够更新状态。"""
        state = ConversationState(session_id="test-session")
        intent = IntentResult(main_intent="order_query", sub_intent="order_query.query_status")
        result = state_tracker.apply(state, intent)
        assert result.current_main_intent == "order_query"
        assert result.current_sub_intent == "order_query.query_status"
