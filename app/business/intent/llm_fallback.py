from __future__ import annotations

import json
from typing import Any, get_args

from pydantic import BaseModel, Field, model_validator

from app.config import LLMConfig
from app.schema import IntentResult
from app.schema.intent import (
    MAIN_INTENT_CODES,
    SUB_INTENT_CODES,
    MainIntentCode,
    SubIntentCode,
    EmotionLabel,
    EmotionState,
)
from app.business.prompts import LLM_INTENT_SYSTEM_PROMPT, build_llm_intent_user_prompt
from app.utils.module_logger import _tagged, get_module_logger

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None

logger = get_module_logger("intent")

# Valid values the router actually uses (derived from the single source of truth)
VALID_MAIN = set(MAIN_INTENT_CODES)
VALID_SUB = set(SUB_INTENT_CODES)
VALID_EMOTIONS = frozenset(get_args(EmotionLabel))


class LLMIntentDecision(BaseModel):
    model_config = {"populate_by_name": True}

    main_intent: MainIntentCode = "unrecognize"
    sub_intent: SubIntentCode = "unrecognize.unknown"

    confidence: float = 0.8
    needs_clarification: bool = False
    reason: str = ""
    slots: dict[str, str] = Field(default_factory=dict)
    emotion: EmotionLabel = "neutral"

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values

        # 单意图归一化：仅做单条 sanitize。
        if values.get("main_intent") in VALID_MAIN:
            single = _normalize_one(values)
            for key in ("main_intent", "sub_intent", "confidence", "needs_clarification", "reason", "slots"):
                if key in single:
                    values[key] = single[key]
            return values

        return _normalize_one(values)


def _normalize_one(values: object) -> dict[str, Any]:
    """把单条意图原始 dict 归一化为 {main_intent, sub_intent, slots, confidence, ...}。"""
    if not isinstance(values, dict):
        return {"main_intent": "unrecognize", "sub_intent": "unrecognize.unknown"}
    values = dict(values)

    # Qwen 可能用 "intent"（点分 "main.sub"）代替 main_intent/sub_intent
    if "intent" in values and "main_intent" not in values:
        intent_val = values.pop("intent")
        if isinstance(intent_val, str) and "." in intent_val:
            values["main_intent"] = intent_val.split(".")[0]
            values["sub_intent"] = intent_val
        elif isinstance(intent_val, str):
            values["main_intent"] = intent_val

    if values.get("main_intent") not in VALID_MAIN:
        si = values.get("sub_intent", "")
        if isinstance(si, str) and "." in si:
            values["main_intent"] = si.split(".")[0]
        else:
            values["main_intent"] = "unrecognize"

    if values.get("sub_intent") not in VALID_SUB:
        mi = values.get("main_intent", "unrecognize")
        guesses = {
            "order_query": "order_query.query_status",
            "logistics": "logistics.not_received",
            "after_sale_refund": "after_sale_refund.no_reason_return",
            "complaint": "complaint.service_complaint",
            "handoff_service": "handoff_service.request_human",
            "unrecognize": "unrecognize.unknown",
            "unsupported_biz": "unsupported_biz.out_of_scope",
        }
        values["sub_intent"] = guesses.get(mi, "unrecognize.unknown")

    values.setdefault("confidence", 0.8)
    values.setdefault("needs_clarification", False)
    values.setdefault("reason", "")
    raw_slots = values.get("slots")
    values["slots"] = raw_slots if isinstance(raw_slots, dict) else {}
    emo = values.get("emotion")
    values["emotion"] = emo if emo in VALID_EMOTIONS else "neutral"
    return values


class LLMIntentFallbackService:
    @classmethod
    def from_env(cls, use_llm: bool = True) -> LLMIntentFallbackService:
        from app.config import load_llm_config
        config = load_llm_config()
        return cls(config, use_llm=use_llm)

    def __init__(self, config: LLMConfig, use_llm: bool = True) -> None:
        self.config = config
        self.client = None

        if not use_llm:
            logger.info(_tagged("intent", "LLM fallback disabled: use_llm=False"))
            return
        if AsyncOpenAI is None:
            logger.warning(_tagged("intent", "LLM fallback disabled: openai SDK not installed"))
            return
        if not config.is_usable:
            logger.info(_tagged("intent", "LLM fallback disabled: api_key not configured"))
            return

        client_kwargs: dict[str, object] = {
            "api_key": config.api_key,
            "timeout": config.timeout_seconds,
        }
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = AsyncOpenAI(**client_kwargs)
        logger.info(_tagged("intent", "LLMIntentFallbackService initialized model=%s (async)"), config.model)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def classify(self, message: str, state: ConversationState) -> IntentResult | None:
        if self.client is None:
            logger.debug(_tagged("intent", "LLM fallback skipped: client not available"))
            return None

        # 从状态对象借用上下文（上下文隔离：只取上一轮子意图）。
        previous_sub_intent = state.current_sub_intent
        logger.debug(
            _tagged("intent", "LLM fallback classify message=%r previous_sub_intent=%s"),
            message[:80], previous_sub_intent,
        )
        try:
            prompt = build_llm_intent_user_prompt(message, state=state)
            parsed = await self._classify_with_chat_completions(prompt)
        except Exception as exc:
            logger.warning(_tagged("intent", "LLM fallback classify crashed: %s"), repr(exc))
            return None

        if parsed is None:
            logger.info(_tagged("intent", "LLM fallback: parsing failed, returning None"))
            return None

        if parsed.confidence < self.config.confidence_threshold:
            logger.info(
                _tagged("intent", "LLM fallback: confidence=%.2f below threshold=%.2f, discarding"),
                parsed.confidence, self.config.confidence_threshold,
            )
            return None

        logger.info(
            _tagged("intent", "LLM fallback success: intent=%s.%s confidence=%.2f"),
            parsed.main_intent, parsed.sub_intent, parsed.confidence,
        )
        return IntentResult(
            main_intent=parsed.main_intent,
            sub_intent=parsed.sub_intent,
            confidence=parsed.confidence,
            slots=parsed.slots,
            needs_clarification=parsed.needs_clarification,
            # LLM 仅产出情绪标签（字符串），需包成 EmotionState 与 IntentResult 对齐。
            emotion=EmotionState(primary=parsed.emotion, confidence=0.8),
            route_source="llm_fallback",
        )

    async def _classify_with_chat_completions(self, prompt: str) -> LLMIntentDecision | None:
        """Call chat.completions (async) and parse the JSON response."""
        try:
            # 生成参数（thinking 等）统一走 LLMConfig，默认关闭思维链以降延迟。
            gen_kwargs = self.config.generation_kwargs()
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": LLM_INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                stream=False,
                **gen_kwargs,
            )
        except Exception as exc:
            logger.warning(_tagged("intent", "chat.completions API error: %s"), repr(exc))
            return None

        content = response.choices[0].message.content if response.choices else None
        if not content:
            logger.warning(_tagged("intent", "chat.completions returned empty content"))
            return None

        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            start = 1 if len(lines) > 1 and lines[0].startswith("```") else 0
            end = -1 if len(lines) > 1 and lines[-1].strip() == "```" else len(lines)
            content = "\n".join(lines[start:end]).strip()

        try:
            data: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning(_tagged("intent", "chat.completions JSON decode error: %s raw=%s"), repr(exc), content[:200])
            return None

        # 单意图：按 main_intent / sub_intent 字段归一化
        primary = _normalize_one(data)

        if primary["main_intent"] not in VALID_MAIN:
            logger.warning(_tagged("intent", "LLM returned invalid main_intent=%s, discarding"), primary["main_intent"])
            return None
        if primary["sub_intent"] not in VALID_SUB:
            logger.warning(_tagged("intent", "LLM returned invalid sub_intent=%s, discarding"), primary["sub_intent"])
            return None

        try:
            parsed = LLMIntentDecision(**primary)
            logger.debug(_tagged("intent", "chat.completions success: %s"), content[:100])
            return parsed
        except Exception as exc:
            logger.warning(_tagged("intent", "LLMIntentDecision construction error: %s primary=%s"), repr(exc), primary)
            return None

    def _safe_dump(self, response: object) -> str:
        if hasattr(response, "model_dump_json"):
            try:
                return response.model_dump_json(indent=2)
            except Exception:
                pass
        return repr(response)
