"""测试对话服务（RAG 工具化改造后）。"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import LLMConfig
from app.schema import ConversationState, EmotionState, ToolExecutionResult
from app.business.dialog import ClarificationService, ResponseService
from app.business.agent.agent_node import AgentNodeService
from app.business.tools.tool_executor import ToolExecutor


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


class TestDialogServices:
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

    def test_generation_kwargs_should_pass_thinking_and_temperature(self):
        """LLMConfig 的 enable_thinking/temperature 应原样透传到 chat.completions.create。"""
        config = LLMConfig(enable_thinking=True, temperature=0.5, max_tokens=512, top_p=0.9)
        llm_client = AsyncMock()
        llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="追问文案"))]
        )
        service = ClarificationService(
            llm_client=llm_client,
            llm_model="fake-model",
            llm_config=config,
        )
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            current_action="ask_slot_clarification",
        )
        state.missing_slots = ["order_id"]
        asyncio.run(service.generate(state))

        _, kwargs = llm_client.chat.completions.create.call_args
        assert kwargs.get("extra_body") == {"enable_thinking": True}
        assert kwargs.get("temperature") == 0.5
        assert kwargs.get("max_tokens") == 512
        assert kwargs.get("top_p") == 0.9

    def test_default_llm_config_should_disable_thinking(self):
        """默认 LLMConfig 应关闭思维链（enable_thinking=False），避免推理开销。"""
        config = LLMConfig()
        assert config.enable_thinking is False
        gen = config.generation_kwargs()
        assert gen.get("extra_body") == {"enable_thinking": False}
        # 未显式设置的采样参数不应出现
        assert "temperature" not in gen
        assert "max_tokens" not in gen
        assert "top_p" not in gen

    def test_agent_node_should_not_leak_scheduler_monologue_to_reply(self):
        """agent_node 是调度节点，其 content 输出只是内部决策旁白，绝不能当作面向用户的
        state.reply 输出（否则会把「直接结束本节点、由回复节点…」这类内部 monologue 漏给用户）。
        用户回复统一由 response_generator 基于上下文生成。"""
        llm_client = AsyncMock()
        # LLM 直接返回 content、无 tool_calls（典型的「内部决策旁白」场景）
        llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="调度节点：信息不足，直接结束本节点，由回复节点向用户索要订单号。", tool_calls=None))]
        )

        service = AgentNodeService(
            llm_client=llm_client,
            llm_model="fake-model",
            tool_executor=ToolExecutor(),
            max_tool_rounds=3,
        )
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        state.recent_messages.append({"role": "user", "content": "把订单 A1001 退掉"})
        result = asyncio.run(service.run(state))

        # 调度节点的自言自语绝不能成为用户可见的回复
        assert result.reply == ""
        # 但调度决策本身（调用 LLM）照常发生
        llm_client.chat.completions.create.assert_called()

    def test_response_generator_should_skip_llm_when_reply_present(self):
        """response_generator 在 state.reply 已存在时应直接返回，不再调用 LLM（去冗余）。"""
        llm_client = AsyncMock()
        llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="不应出现"))]
        )
        service = ResponseService(
            llm_client=llm_client,
            llm_model="fake-model",
        )
        state = ConversationState(session_id="test-session", user_id=1, channel="web")
        state.reply = "已由 agent_node 生成"
        result = asyncio.run(service.generate(state))
        assert result.reply == "已由 agent_node 生成"
        # 不应再调用 LLM
        llm_client.chat.completions.create.assert_not_called()

    def test_response_generator_fills_template_from_yaml(self):
        """决策层产出的 tool_result 由生成节点按 yml 模板填值产出 reply，不调 LLM（去冗余）。"""
        prompt_registry = MagicMock()
        prompt_registry.get.return_value = {}
        prompt_registry.get_tool_template.return_value = "订单 {order_id} 当前状态为 {status}，金额 {amount} 元。"
        llm_client = AsyncMock()
        service = ResponseService(prompt_registry=prompt_registry, llm_client=llm_client, llm_model="fake-model")
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            tool_results=[ToolExecutionResult(
                tool="query_order", kind="success",
                raw_result={"order_id": "A1001", "status": "已发货", "product_name": "键盘", "amount": 199.0},
                sanitized_result={"order_id": "A1001", "status": "已发货", "product_name": "键盘", "amount": 199.0},
            )],
        )
        result = asyncio.run(service.generate(state))
        assert result.reply == "订单 A1001 当前状态为 已发货，金额 199.0 元。"
        # 命中模板 → 不调 LLM
        llm_client.chat.completions.create.assert_not_called()

    def test_response_generator_falls_back_to_llm_when_no_template(self):
        """无匹配模板（新工具/开放问答）时，生成节点退回 LLM 生成。"""
        prompt_registry = MagicMock()
        prompt_registry.get.return_value = {}
        prompt_registry.get_tool_template.return_value = None
        llm_client = AsyncMock()
        llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="LLM 兜底回复。"))]
        )
        service = ResponseService(prompt_registry=prompt_registry, llm_client=llm_client, llm_model="fake-model")
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            tool_results=[ToolExecutionResult(tool="unknown_tool", kind="success", raw_result={"x": 1})],
        )
        result = asyncio.run(service.generate(state))
        assert result.reply == "LLM 兜底回复。"
        llm_client.chat.completions.create.assert_called()

    def test_response_generator_falls_back_to_llm_when_rag_empty(self):
        """RAG 检索为空（count=0）时，模板「检索到 0 条相关文档」不是有效回复，
        生成节点应跳过模板、退回 LLM 生成，而非把空检索结果当答案。"""
        prompt_registry = MagicMock()
        prompt_registry.get.return_value = {}
        prompt_registry.get_tool_template.return_value = "检索到 {count} 条相关文档。"
        llm_client = AsyncMock()
        llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="LLM 兜底回复。"))]
        )
        service = ResponseService(prompt_registry=prompt_registry, llm_client=llm_client, llm_model="fake-model")
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            tool_results=[ToolExecutionResult(
                tool="rag_retrieve", kind="success",
                raw_result={"retrieved_docs": [], "count": 0},
                sanitized_result={"retrieved_docs": [], "count": 0},
            )],
        )
        result = asyncio.run(service.generate(state))
        assert result.reply == "LLM 兜底回复。"
        llm_client.chat.completions.create.assert_called()

    def test_response_generator_aggregates_multiple_tool_results(self):
        """多工具结果聚合：``tool_results`` 含多个可模板化的结果时，按序拼接、互不覆盖。"""
        prompt_registry = MagicMock()
        prompt_registry.get.return_value = {}
        prompt_registry.get_tool_template.side_effect = (
            lambda tool, kind: "订单 {order_id} 状态：{status}。"
            if tool == "query_order"
            else "物流：{tracking_status}。"
        )
        llm_client = AsyncMock()
        service = ResponseService(prompt_registry=prompt_registry, llm_client=llm_client, llm_model="fake-model")
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            tool_results=[
                ToolExecutionResult(
                    tool="query_order", kind="success",
                    raw_result={"order_id": "A1001", "status": "已发货"},
                    sanitized_result={"order_id": "A1001", "status": "已发货"},
                ),
                ToolExecutionResult(
                    tool="query_logistics", kind="success",
                    raw_result={"order_id": "A1001", "tracking_status": "运输中"},
                    sanitized_result={"order_id": "A1001", "tracking_status": "运输中"},
                ),
            ],
        )
        result = asyncio.run(service.generate(state))
        assert "订单 A1001 状态：已发货。" in result.reply
        assert "物流：运输中。" in result.reply
        # 命中模板聚合 → 不调 LLM
        llm_client.chat.completions.create.assert_not_called()

    def test_sanitize_masks_sensitive_fields(self):
        """sanitize_tool_result 对手机号/身份证/地址/姓名/邮箱做掩码，其余原样。"""
        from app.business.tools.sanitize import sanitize_tool_result

        raw = {
            "phone": "13800138000",
            "id_card": "110101199001011234",
            "address": "北京市海淀区中关村大街1号",
            "name": "张三",
            "email": "zhangsan@example.com",
            "order_id": "A1001",
            "status": "已发货",
        }
        sanitized = sanitize_tool_result(raw)
        assert sanitized["phone"] == "138****8000"
        assert sanitized["id_card"].endswith("1234") and sanitized["id_card"].startswith("****")
        assert sanitized["address"].startswith("北京市海淀") and "****" in sanitized["address"]
        assert sanitized["name"] == "张****"
        assert sanitized["email"] == "z****n@example.com"
        # 非敏感字段原样
        assert sanitized["order_id"] == "A1001"
        assert sanitized["status"] == "已发货"
        # 副本而非同一对象
        assert sanitized is not raw


class TestEmotionSoothing:
    """先安抚后回答：negative 情绪回复确定性加安抚前缀（见 plans/emotion-recognition-soothing-plan.md）。"""

    PREFIX = "非常抱歉给你带来不好的体验，"

    def _service_with_prefix(self, prefix: str | None = PREFIX):
        prompt_registry = MagicMock()
        prompt_registry.get.return_value = {}
        prompt_registry.get_tool_template.return_value = None
        prompt_registry.get_empathy_prefix.return_value = prefix
        llm_client = AsyncMock()
        llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="这是回复正文。"))]
        )
        return ResponseService(prompt_registry=prompt_registry, llm_client=llm_client, llm_model="fake-model")

    def test_negative_adds_empathy_prefix_llm_fallback(self):
        """negative + LLM 兜底答案 → reply 以安抚前缀开头。"""
        service = self._service_with_prefix()
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="negative", confidence=0.9),
        )
        result = asyncio.run(service.generate(state))
        assert result.reply.startswith(self.PREFIX)
        assert "这是回复正文。" in result.reply

    def test_negative_adds_empathy_prefix_template(self):
        """negative + 模板答案 → reply 以安抚前缀开头（模板路径也覆盖）。"""
        prompt_registry = MagicMock()
        prompt_registry.get.return_value = {}
        prompt_registry.get_tool_template.return_value = "订单 {order_id} 状态：{status}。"
        prompt_registry.get_empathy_prefix.return_value = self.PREFIX
        llm_client = AsyncMock()
        service = ResponseService(prompt_registry=prompt_registry, llm_client=llm_client, llm_model="fake-model")
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="negative", confidence=0.9),
            tool_results=[ToolExecutionResult(
                tool="query_order", kind="success",
                raw_result={"order_id": "A1001", "status": "已发货"},
                sanitized_result={"order_id": "A1001", "status": "已发货"},
            )],
        )
        result = asyncio.run(service.generate(state))
        assert result.reply.startswith(self.PREFIX)
        assert "订单 A1001 状态：已发货。" in result.reply

    def test_preset_reply_also_soothed(self):
        """negative + 其它节点预置回复（early-return 路径）→ 也加前缀（澄清也要先安抚）。"""
        service = self._service_with_prefix()
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="negative", confidence=0.9),
            reply="请提供订单号",
        )
        result = asyncio.run(service.generate(state))
        assert result.reply.startswith(self.PREFIX)
        assert "请提供订单号" in result.reply

    def test_positive_not_soothed(self):
        """positive → 不加前缀。"""
        service = self._service_with_prefix()
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="positive", confidence=0.85),
        )
        result = asyncio.run(service.generate(state))
        assert not result.reply.startswith(self.PREFIX)
        assert result.reply == "这是回复正文。"

    def test_neutral_not_soothed(self):
        """neutral → 不加前缀。"""
        service = self._service_with_prefix()
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="neutral", confidence=0.6),
        )
        result = asyncio.run(service.generate(state))
        assert not result.reply.startswith(self.PREFIX)

    def test_idempotent_no_duplicate_prefix(self):
        """已含前缀的 reply 不重复拼接（幂等）。"""
        service = self._service_with_prefix()
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="negative", confidence=0.9),
            reply=self.PREFIX + "请提供订单号",
        )
        result = asyncio.run(service.generate(state))
        # 仅一个前缀，不重复
        assert result.reply.count(self.PREFIX) == 1
        assert result.reply == self.PREFIX + "请提供订单号"

    def test_missing_prefix_config_skips(self):
        """yml 未配 empathy_prefix → 不加前缀（不硬依赖）。"""
        service = self._service_with_prefix(prefix=None)
        state = ConversationState(
            session_id="test-session", user_id=1, channel="web",
            emotion=EmotionState(primary="negative", confidence=0.9),
        )
        result = asyncio.run(service.generate(state))
        assert not result.reply.startswith(self.PREFIX)


