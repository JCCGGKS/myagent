from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.schema import ConversationState
from app.business.prompts import build_clarification_system_prompt
from app.utils import build_action_record, load_yaml_file
from app.utils.config_paths import get_config_dir
from app.utils.llm import call_llm

logger = logging.getLogger(__name__)

DEFAULT_CLARIFICATION_PROMPT_PATH = get_config_dir() / "clarification_prompts.yml"


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
        """调用 LLM 生成澄清话术（需配置真实 LLM client）。失败时返回空串，由上层模板兜底。"""
        logger.debug("ClarificationService: calling LLM")
        result = call_llm(
            self.llm_client,
            self.llm_model,
            [{"role": "system", "content": system_prompt}],
            fallback_content="",
        )
        return result["content"].strip()
