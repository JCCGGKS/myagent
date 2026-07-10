from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.schema import ChatRequest, ConversationState

logger = logging.getLogger(__name__)
from app.dao import SessionStore
from app.business.prompts import build_response_system_prompt
from app.utils import build_action_record, load_yaml_file
from app.utils.config_paths import get_config_dir


DEFAULT_CLARIFICATION_PROMPT_PATH = (
    get_config_dir() / "clarification_prompts.yml"
)
DEFAULT_RESPONSE_PROMPT_PATH = (
    get_config_dir() / "response_prompts.yml"
)


class ClarificationPromptRegistry:
    def __init__(self, prompt_path: Optional[Path] = None) -> None:
        self.prompt_path = prompt_path or DEFAULT_CLARIFICATION_PROMPT_PATH
        self._prompts = self._load()

    def get(self) -> dict:
        return self._prompts

    def _load(self) -> dict:
        data = load_yaml_file(self.prompt_path)
        prompts = data.get("clarification_prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError(f"Invalid clarification prompt config: {self.prompt_path}")
        return prompts


class ResponsePromptRegistry:
    def __init__(self, prompt_path: Optional[Path] = None) -> None:
        self.prompt_path = prompt_path or DEFAULT_RESPONSE_PROMPT_PATH
        self._prompts = self._load()

    def get(self) -> dict:
        return self._prompts

    def _load(self) -> dict:
        data = load_yaml_file(self.prompt_path)
        prompts = data.get("response_prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError(f"Invalid response prompt config: {self.prompt_path}")
        return prompts


class ClarificationService:
    def __init__(self, prompt_registry: Optional[ClarificationPromptRegistry] = None) -> None:
        self.prompt_registry = prompt_registry or ClarificationPromptRegistry()

    def generate(self, state: ConversationState) -> ConversationState:
        prompts = self.prompt_registry.get()
        if state.current_action == "ask_intent_clarification":
            state.reply = prompts["intent_clarification"]
        elif "order_id" in state.missing_slots:
            state.reply = prompts.get("slot_clarification", {}).get(
                state.current_main_intent,
                prompts["generic_slot_clarification"],
            )
        else:
            state.reply = prompts["generic_fallback"]
        state.latest_action_name = "clarification_node"
        state.latest_action_result = {"reply": state.reply}
        state.action_history.append(build_action_record("clarification_node", state.reply))
        return state


class ResponseService:
    def __init__(
        self,
        prompt_registry: Optional[ResponsePromptRegistry] = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
    ) -> None:
        self.prompt_registry = prompt_registry or ResponsePromptRegistry()
        self.llm_client = llm_client
        self.llm_model = llm_model

    def generate(self, state: ConversationState) -> ConversationState:
        """生成响应（由真实 LLM 驱动）。"""
        # 如果已经有 reply（如 agent_node 已生成），直接返回
        if state.reply:
            return state

        # 构造 LLM 输入
        system_prompt = build_response_system_prompt(state)
        messages = self._build_messages(state)
        # messages 第一个位置是 system，剩余是 user/assistant
        llm_messages = [{"role": "system", "content": system_prompt}] + messages

        # 调用 LLM 生成响应
        reply = self._call_llm(llm_messages, state)

        state.reply = reply
        state.latest_action_name = "response_generator"
        state.latest_action_result = {"reply": reply}
        if not state.action_history or state.action_history[-1].action_name != "response_generator":
            state.action_history.append(build_action_record("response_generator", reply))
        return state

    def _build_messages(self, state: ConversationState) -> list[dict]:
        """构造 messages（包含历史消息）。"""
        # 加入最近 5 条消息
        return list(state.message_history[-5:])

    def _call_llm(self, messages: list[dict], state: Optional[ConversationState] = None) -> str:
        """调用 LLM 生成响应（需配置真实 LLM client）。"""
        logger.debug("ResponseService: calling LLM with %d messages", len(messages))
        if self.llm_client is None or not self.llm_model:
            raise RuntimeError(
                "LLM client is not configured; a real LLM client is required "
                "to generate responses."
            )

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ResponseService: LLM call failed err=%r", exc)
            return "抱歉，我暂时无法回答这个问题。"

        content = (response.choices[0].message.content or "") if response.choices else ""
        return content.strip() or "抱歉，我暂时无法回答这个问题。"


class MessageService:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def persist(self, state: ConversationState, request: ChatRequest) -> ConversationState:
        self.store.append_message(state.session_id, "user", request.message)
        self.store.append_message(
            state.session_id,
            "assistant",
            state.reply,
            message_type="clarification" if state.current_action.startswith("ask_") else "text",
        )

        if state.tool_result:
            self.store.record_tool_call(
                session_id=state.session_id,
                tool_name=state.latest_action_name or state.tool_result.kind,
                tool_category=_tool_category(state),
                request_args=dict(state.slots),
                raw_result=state.tool_result.raw_result,
                sanitized_result=state.tool_result.sanitized_result,
                user_facing_summary=state.tool_result.user_facing_summary,
            )

        self.store.save(state)
        return state


def _tool_category(state: ConversationState) -> str:
    if state.current_action == "handoff_human":
        return "workflow"
    return "query"
