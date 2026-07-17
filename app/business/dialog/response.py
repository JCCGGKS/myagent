from __future__ import annotations

from pathlib import Path
from string import Formatter
from typing import Any, Optional

from app.config import LLMConfig
from app.schema import ConversationState
from app.business.prompts import build_response_system_prompt
from app.utils import build_action_record, load_yaml_file
from app.utils.config_paths import get_config_dir
from app.utils.llm import call_llm_async, LLM_CALL_FAILED_REPLY
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("response")

DEFAULT_RESPONSE_PROMPT_PATH = get_config_dir() / "response_prompts.yml"


class _SafeDict(dict):
    """占位符缺失时填空串而非抛异常，容忍模板与数据字段不齐。"""

    def __missing__(self, key: str) -> str:  # noqa: D401
        return ""


def _safe_format(template: str, data: dict) -> str:
    """用 ``data`` 填值模板，缺失字段留空、不抛异常。"""
    return Formatter().vformat(template, (), _SafeDict(data))


class ResponsePromptRegistry:
    def __init__(self, prompt_path: Optional[Path] = None) -> None:
        self.prompt_path = prompt_path or DEFAULT_RESPONSE_PROMPT_PATH
        self._data = self._load()

    def get(self) -> dict:
        """对话/兜底示例（few-shot），供 LLM 生成时注入提示词。"""
        return self._data.get("response_prompts", {})

    def get_tool_template(self, tool: str, kind: str) -> str | None:
        """按 tool + kind 取工具结果的话术模板；无匹配返回 None（走 LLM 兜底）。"""
        return self._data.get("tool_response_templates", {}).get(tool, {}).get(kind)

    def get_empathy_prefix(self, emotion: str) -> str | None:
        """取指定情绪的安抚前缀；未配置（如 positive/neutral）返回 None。"""
        return self._data.get("empathy_prefix", {}).get(emotion)

    def _load(self) -> dict:
        data = load_yaml_file(self.prompt_path)
        if "response_prompts" not in data or not isinstance(data["response_prompts"], dict):
            raise ValueError(f"Invalid response prompt config: {self.prompt_path}")
        return data


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
        """生成响应（由真实 LLM 驱动，异步）。

        职责：成为 ``state.reply`` 的唯一写入方。
        - 已有 reply（agent_node 直答 / 澄清节点产出）→ 早返回（去冗余，不调 LLM）；
        - 决策层产出的 ``tool_results`` → 按 yml 模板填值产出回复（不调 LLM，保留去冗余收益）；
          单结果等价原逻辑；多结果做聚合（模板拼接 / RAG 文档走 LLM 综述）；
        - 无匹配模板（新工具/开放问答）→ LLM 兜底生成。
        """
        # 其他节点（澄清/直答）已设回复则尊重，直接返回（去冗余）。
        logger.info(_tagged("response", "generate start session=%s has_reply=%s n_tool=%s"), state.session_id, bool(state.reply), len(state.tool_results))
        if state.reply:
            self._apply_empathy_prefix(state)
            return state

        # 决策层只产 tool_results（结构化列表），不写 reply；本节点按 yml 模板填值产出 reply。
        results = state.tool_results or []
        if results:
            if len(results) == 1:
                piece = self._try_template(results[0])
                if piece is not None:
                    state.reply = piece
                    self._apply_empathy_prefix(state)
                    if not state.action_history or state.action_history[-1].action_name != "response_generator":
                        state.action_history.append(build_action_record("response_generator", piece))
                    logger.info(_tagged("response", "generate end session=%s source=template tool=%s kind=%s"), state.session_id, results[0].tool, results[0].kind)
                    return state
                # 模板取不到 → 落到下方 LLM 兜底
            elif len(results) > 1:
                parts: list[str] = []
                has_rag_docs = False
                for r in results:
                    # RAG 检索有文档时走下方 LLM 综述（_build_messages 已汇聚文档），不在此拼接。
                    if r.tool == "rag_retrieve" and (r.sanitized_result or {}).get("count"):
                        has_rag_docs = True
                        continue
                    piece = self._try_template(r)
                    if piece:
                        parts.append(piece)
                if not has_rag_docs and parts:
                    state.reply = "\n".join(parts)
                    self._apply_empathy_prefix(state)
                    if not state.action_history or state.action_history[-1].action_name != "response_generator":
                        state.action_history.append(build_action_record("response_generator", state.reply))
                    logger.info(_tagged("response", "generate end session=%s source=template_multi n=%d"), state.session_id, len(parts))
                    return state
                # 含 RAG 文档 或 全部模板缺失 → 落到下方 LLM 兜底（综述/生成）

        # 构造 LLM 输入
        examples = self._build_response_examples(state)
        system_prompt = build_response_system_prompt(state, examples=examples)
        messages = self._build_messages(state)
        # messages 第一个位置是 system，剩余是 user/assistant
        llm_messages = [{"role": "system", "content": system_prompt}] + messages

        # 调用 LLM 生成响应（异步 await）
        reply = await self._call_llm(llm_messages, state)

        state.reply = reply
        self._apply_empathy_prefix(state)
        if not state.action_history or state.action_history[-1].action_name != "response_generator":
            state.action_history.append(build_action_record("response_generator", reply))
        logger.info(_tagged("response", "generate end session=%s source=llm"), state.session_id)
        return state

    def _try_template(self, result: "ToolExecutionResult | None") -> str | None:
        """对单条工具结果试取话术模板；取不到（新工具/开放问答）返回 None 走 LLM 兜底。

        - error 优先用 ``raw_result.message`` 模板；
        - ``rag_retrieve`` 空检索（count 为 0/缺失）→ 返回 None 降级 LLM，不把空结果当答案；
        - 其余按 ``tool + kind`` 取模板填值；取不到 → None。
        """
        if result is None:
            return None
        tpl = self.prompt_registry.get_tool_template(result.tool, result.kind)
        if not tpl:
            return None
        data = result.sanitized_result or {}
        # RAG 检索为空（count 为 0/缺失）时，「检索到 0 条相关文档」不是有效的最终
        # 回复，返回 None 降级到下方 LLM 生成（用通用知识作答或向用户澄清），避免把
        # 空检索结果当作答案呈现给用户（见回归 06_工具调用）。
        if result.tool == "rag_retrieve" and not data.get("count"):
            return None
        return _safe_format(tpl, data)

    def _apply_empathy_prefix(self, state: ConversationState) -> None:
        """negative 情绪时在回复前追加安抚前缀（先安抚后回答）。

        仅对 negative 生效（positive/neutral 不加，避免冗余）；自带幂等（已加前缀不重复）。
        前缀来自 ``empathy_prefix.negative`` 配置，缺配置则跳过（不硬依赖）。
        """
        if state.emotion.primary != "negative":
            return
        prefix = self.prompt_registry.get_empathy_prefix("negative")
        if not prefix:
            return
        reply = state.reply or ""
        if reply.startswith(prefix):
            return
        # 前缀以中文标点结尾时直接拼接；否则补一个空格，避免黏连。
        sep = "" if (prefix[-1] in "，。！？、,.;:") else " "
        state.reply = prefix + sep + reply

    def _build_messages(self, state: ConversationState) -> list[dict]:
        """构造 messages（包含历史消息）。

        上下文来自摘要缓冲：running_summary（窗口外已压缩内容）+ recent_messages
        （活动窗口内的近期消息），与 agent_node 保持一致。

        RAG 文档注入：汇聚本轮全部 ``tool_results`` 中 ``rag_retrieve`` 命中的
        ``retrieved_docs``，作为一个瞬时 system 消息（不写入 ``state.recent_messages``），
        支持多 RAG + 其他工具混合场景。
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
        # 汇聚全部 RAG 检索结果，统一注入（多 RAG 调用时合并）。
        rag_docs: list[dict] = []
        for r in state.tool_results or []:
            if r.tool == "rag_retrieve" and (r.sanitized_result or {}).get("count"):
                rag_docs.extend((r.sanitized_result or {}).get("retrieved_docs") or [])
        if rag_docs:
            formatted = "\n\n".join(
                f"【参考文档 {i+1}】\n{doc.get('content', '')}" for i, doc in enumerate(rag_docs)
            )
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是检索到的知识库文档，请基于其生成回复：\n{formatted}",
                }
            )
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
        logger.debug(_tagged("response", "calling LLM with %d messages session=%s"), len(messages), state.session_id if state else None)
        result = await call_llm_async(
            self.llm_client,
            self.llm_model,
            messages,
            generation_kwargs=self.generation_kwargs,
        )
        return result["content"].strip() or LLM_CALL_FAILED_REPLY
