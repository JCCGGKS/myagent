from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.schema import ConversationState

logger = logging.getLogger(__name__)
from app.dao import SessionStore
from app.business.prompts import build_clarification_system_prompt, build_response_system_prompt
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
    def __init__(
        self,
        prompt_registry: Optional[ClarificationPromptRegistry] = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
    ) -> None:
        self.prompt_registry = prompt_registry or ClarificationPromptRegistry()
        self.llm_client = llm_client
        self.llm_model = llm_model

    def generate(self, state: ConversationState) -> ConversationState:
        # 优先用澄清提示词走 LLM 生成追问话术
        if self.llm_client is not None and self.llm_model:
            examples = self._build_clarification_examples(state)
            reply = self._call_llm(build_clarification_system_prompt(state, examples=examples))
            if reply:
                state.reply = reply
                state.latest_action_name = "clarification_node"
                state.latest_action_result = {"reply": reply}
                state.action_history.append(build_action_record("clarification_node", reply))
                return state

    def _build_clarification_examples(self, state: ConversationState) -> str | None:
        """把 clarification_prompts.yml 的全部模板整理为示例注入提示词。

        完全配置驱动：yml 中新增任何键（含 slot_clarification 下的子项）都会
        自动作为示例传给 LLM，无需改代码。
        """
        prompts = self.prompt_registry.get()
        flat: list[str] = []
        for value in prompts.values():
            if isinstance(value, str):
                flat.append(value)
            elif isinstance(value, dict):
                flat.extend(v for v in value.values() if isinstance(v, str))
        flat = [v for v in flat if v]
        return "\n".join(f"- {v}" for v in flat) if flat else None

        # 无 LLM client 时回退到模板
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

    def _call_llm(self, system_prompt: str) -> str:
        """调用 LLM 生成澄清话术（需配置真实 LLM client）。"""
        logger.debug("ClarificationService: calling LLM")
        if self.llm_client is None or not self.llm_model:
            raise RuntimeError(
                "LLM client is not configured; a real LLM client is required "
                "to generate clarifications."
            )
        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "system", "content": system_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ClarificationService: LLM call failed err=%r", exc)
            return ""
        content = (response.choices[0].message.content or "") if response.choices else ""
        return content.strip()


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
        examples = self._build_response_examples(state)
        system_prompt = build_response_system_prompt(state, examples=examples)
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
        """构造 messages（包含历史消息）。

        上下文来自摘要缓冲：running_summary（窗口外已压缩内容）+ recent_messages
        （活动窗口内的近期消息），与 agent_node 保持一致。
        """
        messages: list[dict] = []
        if state.running_summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是此前的对话摘要（已压缩）：\n{state.running_summary}",
                }
            )
        messages.extend(state.recent_messages)
        return messages

    def _build_response_examples(self, state: ConversationState) -> str | None:
        """把 response_prompts.yml 中的全部示例注入提示词。

        完全配置驱动：在 yml 中新增任意键，LLM 即可收到，无需改代码。
        """
        prompts = self.prompt_registry.get()
        if not prompts:
            return None
        lines = [f"- {v}" for v in prompts.values() if isinstance(v, str) and v]
        return "\n".join(lines) if lines else None

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


def _tool_category(state: ConversationState) -> str:
    if state.current_action == "handoff_human":
        return "workflow"
    return "query"


class MessageService:
    """对话消息持久化：把用户消息、助手回复、工具调用写入 SessionStore。"""

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
