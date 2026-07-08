from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.config import LLMConfig
from app.models import IntentResult
from app.prompts import LLM_INTENT_SYSTEM_PROMPT, build_llm_intent_user_prompt

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

logger = logging.getLogger(__name__)


class LLMIntentDecision(BaseModel):
    model_config = {"populate_by_name": True}

    main_intent: Literal[
        "faq",
        "order_service",
        "logistics_service",
        "refund_service",
        "handoff_service",
        "chitchat",
        "unsupported",
    ]
    sub_intent: Literal[
        "faq.general",
        "order_service.query_status",
        "logistics_service.query_status",
        "refund_service.consult_policy",
        "refund_service.request_refund",
        "handoff_service.request_human",
        "chitchat.greeting",
        "chitchat.thanks",
        "unsupported.unknown",
    ]
    confidence: float
    needs_clarification: bool = False
    reason: str = ""


class LLMIntentFallbackService:
    @classmethod
    def from_env(cls) -> LLMIntentFallbackService:
        from app.config import load_llm_config
        config = load_llm_config()
        return cls(config)

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.client = None

        if OpenAI is None:
            logger.warning("LLM fallback disabled: openai SDK not installed")
            return
        if not config.is_usable:
            logger.info("LLM fallback disabled: api_key not configured")
            return

        client_kwargs: dict[str, object] = {
            "api_key": config.api_key,
            "timeout": config.timeout_seconds,
        }
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = OpenAI(**client_kwargs)
        logger.info("LLMIntentFallbackService initialized model=%s", config.model)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def classify(self, message: str, previous_sub_intent: str) -> IntentResult | None:
        if self.client is None:
            logger.debug("LLM fallback skipped: client not available")
            return None

        logger.debug(
            "LLM fallback classify message=%r previous_sub_intent=%s",
            message[:80], previous_sub_intent,
        )
        prompt = build_llm_intent_user_prompt(message, previous_sub_intent)
        parsed = self._classify_with_responses_api(prompt)
        if parsed is None:
            parsed = self._classify_with_chat_completions(prompt)

        if parsed is None:
            logger.warning("LLM fallback: both APIs failed, returning None")
            return None

        if parsed.confidence < self.config.confidence_threshold:
            logger.info(
                "LLM fallback: confidence=%.2f below threshold=%.2f, discarding",
                parsed.confidence, self.config.confidence_threshold,
            )
            return None

        logger.info(
            "LLM fallback success: intent=%s.%s confidence=%.2f",
            parsed.main_intent, parsed.sub_intent, parsed.confidence,
        )
        return IntentResult(
            main_intent=parsed.main_intent,
            sub_intent=parsed.sub_intent,
            confidence=parsed.confidence,
            needs_clarification=parsed.needs_clarification,
            route_source="llm_fallback",
        )

    def _classify_with_responses_api(self, prompt: str) -> LLMIntentDecision | None:
        try:
            response = self.client.responses.parse(
                model=self.config.model,
                input=[
                    {"role": "system", "content": LLM_INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                text_format=LLMIntentDecision,
            )
        except Exception as exc:
            logger.warning("responses.parse API error: %s", repr(exc))
            return None

        parsed = response.output_parsed
        if parsed is None:
            logger.warning("responses.parse returned empty parsed")
            return None

        logger.debug("responses.parse success: %s", self._safe_dump(response))
        return parsed

    def _classify_with_chat_completions(self, prompt: str) -> LLMIntentDecision | None:
        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": LLM_INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning("chat.completions API error: %s", repr(exc))
            return None

        content = response.choices[0].message.content if response.choices else None
        if not content:
            logger.warning("chat.completions returned empty content")
            return None

        try:
            data = json.loads(content)
            # 兼容 Qwen 返回的字段名（intent/sub_intent）
            if isinstance(data, dict):
                if "intent" in data and "main_intent" not in data:
                    data["main_intent"] = data.pop("intent")
                if "sub_intent" in data and "sub_intent" not in data:
                    data["sub_intent"] = data.pop("sub_intent")
            parsed = LLMIntentDecision(**data)
            logger.debug("chat.completions success: %s", content)
            return parsed
        except Exception as exc:
            logger.warning("chat.completions parse error: %s raw=%s", repr(exc), content)
            return None

    def _safe_dump(self, response: object) -> str:
        if hasattr(response, "model_dump_json"):
            try:
                return response.model_dump_json(indent=2)
            except Exception:
                pass
        return repr(response)
