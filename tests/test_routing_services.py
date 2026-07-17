"""测试路由服务（RAG 工具化改造后）。"""

import asyncio

import pytest
from unittest.mock import MagicMock, patch

from app.schema import ConversationState, IntentResult, EmotionState
from app.business.intent.routing import (
    HandoffClarificationPolicy,
    IntentRouterService,
    StateTrackerService,
)


@pytest.fixture
def router():
    """创建一个测试用的 IntentRouterService 实例。"""
    rule_registry = MagicMock()
    rule_registry.get.return_value = {
        "emotion_keywords": {
            "negative": ["生气", "差评", "太慢了", "没人处理", "无语", "受不了", "受不了了", "太过分了"],
        },
        "routing_rules": [
            {"intent": "handoff_service", "sub_intent": "handoff_service.request_human",
             "keywords": ["转人工", "人工客服"], "confidence": 0.99, "risk_level": "medium", "handoff_reason": "user_request"},
            {"intent": "complaint", "sub_intent": "complaint.service_complaint",
             "keywords": ["投诉", "抱怨"], "emotion": "negative", "confidence": 0.95, "risk_level": "high",
             "handoff_reason": "complaint", "handoff_reason_emotion": "emotion_escalation"},
            {"intent": "logistics", "sub_intent": "logistics.not_received",
             "keywords": ["物流", "快递"], "confidence_with_order": 0.9, "confidence_without_order": 0.78, "needs_order": True},
            {"intent": "order_query", "sub_intent": "order_query.query_status",
             "keywords": ["订单", "下单"], "confidence_with_order": 0.9, "confidence_without_order": 0.76, "needs_order": True},
            {"intent": "after_sale_refund", "sub_intent": "after_sale_refund.consult_policy",
             "action_sub_intent": "after_sale_refund.request_refund",
             "keywords": ["退款", "退货"], "action_keywords": ["申请退款", "办理退货", "退掉"],
             "confidence_with_order": 0.88, "confidence_without_order": 0.8, "needs_clarification_when_no_order": True},
        ],
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


class TestRoutingServices:
    """测试路由服务的核心功能。"""

    def test_intent_router_should_recognize_order_query(self, router):
        """测试能够识别订单查询意图。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "帮我查一下订单 A1001"))
        assert result.main_intent == "order_query"

    def test_intent_router_should_recognize_logistics(self, router):
        """测试能够识别物流查询意图。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "我的快递到哪了"))
        assert result.main_intent == "logistics"

    def test_intent_router_should_recognize_complaint(self, router):
        """测试能够识别投诉意图。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "你们什么破平台，投诉"))
        assert result.main_intent == "complaint"

    def test_intent_router_should_recognize_handoff(self, router):
        """测试能够识别转人工意图。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "转人工"))
        assert result.main_intent == "handoff_service"

    def test_route_should_match_standalone_action_keyword(self, router):
        """强动作词「退掉」只出现在 action_keywords、不含任何基础关键词，也必须能命中
        退款规则并设置 needs_clarification（缺订单号）；否则会漏匹配、退化兜底、
        错过澄清直接进 agent_node 把内部 monologue 漏给用户（见回归 06_工具调用）。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "退掉"))
        assert result.main_intent == "after_sale_refund"
        assert result.needs_clarification is True
        # 缺订单号 → 缺失槽位，下游澄清节点据此向用户索要订单号
        assert result.slots.get("order_id") is None

    def test_route_should_require_clarification_for_bare_refund_keyword(self, router):
        """仅含基础关键词「退款」、不含任何强动作词、缺订单号时，也必须需要澄清
        （向用户索要订单号），而非被当作无需澄清的 consult 直接进 agent_node 触发
        RAG 并以「检索到 0 条相关文档」充当最终回复。与「退掉」动作词行为一致。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "退款"))
        assert result.main_intent == "after_sale_refund"
        assert result.needs_clarification is True
        assert result.slots.get("order_id") is None

    def test_intent_router_should_route_greeting_to_unrecognize(self, router):
        """问候不再单独成意图，无业务关键词时落 unrecognize。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        result = asyncio.run(router.route(state, "你好"))
        assert result.main_intent == "unrecognize"

    def test_route_should_not_ask_order_id_when_inherited(self, router, state_tracker):
        """上一轮已查 A1001、order_id 继承在 state.slots 后，用户只说
        「查订单详情」而未复述单号时，不应再追问订单号。

        回归：routing.py `_build_intent_from_rule` 计算 needs 时必须纳入继承的
        order_id，否则 needs_clarification 残留为 True，LLM 澄清节点会再次发问。
        """
        state = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
            current_main_intent="order_query",
            current_sub_intent="order_query.query_status",
            slots={"order_id": "A1001"},
        )
        intent = asyncio.run(router.route(state, "查订单详情"))
        assert intent.main_intent == "order_query"
        # 意图识别正确，且未因为本轮没复述单号而误判需澄清（修复点）
        assert intent.needs_clarification is False
        # 经 StateTracker 落地后，继承的 order_id 仍在、且不进澄清
        applied = state_tracker.apply(state, intent)
        assert applied.slots.get("order_id") == "A1001"
        assert applied.needs_clarification is False

    def test_policy_should_set_agent_process_for_order_query(self, policy):
        """测试订单查询意图的 policy 决策（需要工具调用）。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web", current_main_intent="order_query")
        result = policy.decide(state)
        assert result.current_action == "agent_process"

    def test_policy_should_set_agent_process_for_logistics(self, policy):
        """测试物流查询意图的 policy 决策（需要工具调用）。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web", current_main_intent="logistics")
        result = policy.decide(state)
        assert result.current_action == "agent_process"

    def test_policy_should_set_agent_process_for_complaint(self, policy):
        """测试投诉意图的 policy 决策（需要工具调用）。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web", current_main_intent="complaint")
        result = policy.decide(state)
        assert result.current_action == "agent_process"

    def test_policy_should_set_answer_directly_for_unrecognize(self, policy):
        """测试未识别意图的 policy 决策（不需要工具）。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web", current_main_intent="unrecognize")
        result = policy.decide(state)
        assert result.current_action == "answer_directly"

    def test_policy_should_not_handoff_when_self_serviceable(self, policy):
        """槽位齐全且工具可用的自助意图，即便历史澄清计数偏高也不强制转人工。

        直接命中 logs/01_test.md 的 Turn 4 症状：已知 A1001 的订单详情完全可答，
        不应因累计澄清计数被升级到人工。
        """
        state = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
            current_main_intent="order_query",
            missing_slots=[],
            needs_clarification=False,
            intent_clarification_count=10,
        )
        result = policy.decide(state)
        assert result.current_action == "agent_process"
        assert result.handoff is False

    def test_policy_should_handoff_after_consecutive_intent_clarification(self, policy):
        """连续 3 次真·听不懂（unrecognize 澄清失败）应强制转人工，兜底保留。"""
        state = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
            current_main_intent="unrecognize",
            needs_clarification=True,
        )
        # 前两次未达阈值
        for _ in range(2):
            result = policy.decide(state)
            assert result.current_action == "ask_intent_clarification"
            assert result.handoff is False
        # 第三次达阈值
        result = policy.decide(state)
        assert result.current_action == "handoff_human"
        assert result.handoff is True

    def test_policy_should_reset_counts_on_resolved_turn(self, policy):
        """解析成功的一轮应清零澄清计数，避免历史包袱滚雪球。"""
        # 先累计一次 intent 澄清失败
        stuck = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
            current_main_intent="unrecognize",
            needs_clarification=True,
        )
        policy.decide(stuck)
        assert stuck.intent_clarification_count == 1
        # 下一轮成功解析（order_query，槽位齐全）→ 计数归零
        resolved = ConversationState(
            session_id="test-session",
            user_id=1,
            channel="web",
            current_main_intent="order_query",
            missing_slots=[],
            needs_clarification=False,
        )
        result = policy.decide(resolved)
        assert resolved.intent_clarification_count == 0
        assert result.current_action == "agent_process"

    def test_state_tracker_should_update_state(self, state_tracker):
        """测试状态跟踪器能够更新状态。"""
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        intent = IntentResult(main_intent="order_query", sub_intent="order_query.query_status")
        result = state_tracker.apply(state, intent)
        assert result.current_main_intent == "order_query"
        assert result.current_sub_intent == "order_query.query_status"


class TestEmotionRecognition:
    """规则 + LLM 双路情绪识别与合并（见 plans/emotion-recognition-soothing-plan.md）。"""

    def test_detect_emotion_negative_keyword(self, router):
        """规则侧：命中负面关键词 → negative。"""
        emo = router._detect_emotion("你们这服务太差了，给个差评")
        assert emo.primary == "negative"

    def test_detect_emotion_neutral_without_keyword(self, router):
        """规则侧：无情绪关键词 → neutral。"""
        emo = router._detect_emotion("帮我查一下订单 A1001")
        assert emo.primary == "neutral"

    def test_detect_emotion_negation_suppresses_negative(self, router):
        """规则侧：否定前缀消歧——「不生气」不应判 negative。"""
        emo = router._detect_emotion("我没生气，只是问问")
        assert emo.primary == "neutral"

    def test_detect_emotion_bu_tai_manyi_falls_to_neutral(self, router):
        """规则侧：含「不太」于否定集——「不太满意」的「满意」被否定 → 回落 neutral
        （不误判 positive）；真实负面可由 LLM 路径补。"""
        emo = router._detect_emotion("我不太满意这次的体验")
        assert emo.primary == "neutral"

    def test_emotion_hit_respects_negation(self, router):
        """_emotion_hit：关键词前有否定前缀则不命中。"""
        assert router._emotion_hit("没投诉", ["投诉"]) is False
        assert router._emotion_hit("投诉", ["投诉"]) is True
        assert router._emotion_hit("我要投诉", ["投诉"]) is True

    def test_merge_emotion_rule_priority(self, router):
        """合并：规则 non-neutral（确定性强）优先于 LLM。"""
        rule = EmotionState(primary="negative", confidence=0.9)
        llm = EmotionState(primary="positive", confidence=0.8)
        assert router._merge_emotion(rule, llm).primary == "negative"

    def test_merge_emotion_llm_fills_blind_spot(self, router):
        """合并：规则 neutral 但 LLM 给情绪 → 取 LLM（补无关键词盲区）。"""
        rule = EmotionState(primary="neutral", confidence=0.6)
        llm = EmotionState(primary="negative", confidence=0.8)
        assert router._merge_emotion(rule, llm).primary == "negative"

    def test_merge_emotion_both_neutral(self, router):
        """合并：都 neutral → neutral。"""
        rule = EmotionState(primary="neutral", confidence=0.6)
        llm = EmotionState(primary="neutral", confidence=0.8)
        assert router._merge_emotion(rule, llm).primary == "neutral"

    def test_merge_emotion_no_llm_returns_rule(self, router):
        """合并：无 LLM 结果 → 取规则。"""
        rule = EmotionState(primary="positive", confidence=0.85)
        assert router._merge_emotion(rule, None).primary == "positive"

    def test_route_keeps_negative_from_memory(self, router):
        """route：本轮合并 neutral 但上一轮 negative → 记忆沿用 negative（衰减）。"""
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="negative", confidence=0.9),
        )
        # 中性问候，无规则/LLM 命中 → 合并 neutral，应被记忆回退为 negative
        intent = asyncio.run(router.route(state, "你好"))
        assert intent.emotion.primary == "negative"
        assert intent.emotion.confidence <= 0.9
