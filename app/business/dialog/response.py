from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.config import LLMConfig
from app.schema import ConversationState
from app.business.prompts import build_response_system_prompt
from app.utils import build_action_record, load_yaml_file
from app.utils.config_paths import get_config_dir
from app.utils.llm import call_llm_async, LLM_CALL_FAILED_REPLY

logger = logging.getLogger(__name__)

DEFAULT_RESPONSE_PROMPT_PATH = get_config_dir() / "response_prompts.yml"


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


class ResponseService:
    def __init__(
        self,
        prompt_registry: Optional[ResponsePromptRegistry] = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self.prompt_registry = prompt_registry or ResponsePromptRegistry()
        self.llm_client = llm_client
        self.llm_model = llm_model
        # 生成参数（thinking/temperature 等），默认关闭思维链。
        self.generation_kwargs = llm_config.generation_kwargs() if llm_config is not None else {}

    async def generate(self, state: ConversationState) -> ConversationState:
        """生成响应（由真实 LLM 驱动，异步）。"""
        # 如果已经有 reply（如 agent_node 已生成），直接返回（去冗余，不再调 LLM）
        if state.reply:
            return state

        # 构造 LLM 输入
        examples = self._build_response_examples(state)
        system_prompt = build_response_system_prompt(state, examples=examples)
        messages = self._build_messages(state)
        # messages 第一个位置是 system，剩余是 user/assistant
        llm_messages = [{"role": "system", "content": system_prompt}] + messages

        # 调用 LLM 生成响应（异步 await）
        reply = await self._call_llm(llm_messages, state)

        state.reply = reply
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

    async def _call_llm(self, messages: list[dict], state: Optional[ConversationState] = None) -> str:
        """调用 LLM 生成响应（需配置真实 LLM client，异步）。失败时兜底为统一道歉语。"""
        logger.debug("ResponseService: calling LLM with %d messages", len(messages))
        result = await call_llm_async(
            self.llm_client,
            self.llm_model,
            messages,
            generation_kwargs=self.generation_kwargs,
        )
        return result["content"].strip() or LLM_CALL_FAILED_REPLY
