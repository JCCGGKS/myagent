from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from app.config import LLMConfig
from app.models import IntentResult
from app.prompts import LLM_INTENT_SYSTEM_PROMPT, build_llm_intent_user_prompt

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


class LLMIntentDecision(BaseModel):
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
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.client = None
        self.last_debug: dict[str, str] = {}

        if OpenAI is None or not config.is_usable:
            self.last_debug = {"status": "disabled_or_sdk_missing"}
            return

        client_kwargs: dict[str, object] = {
            "api_key": config.api_key,
            "timeout": config.timeout_seconds,
        }
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = OpenAI(**client_kwargs)
        self.last_debug = {"status": "ready"}

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def classify(self, message: str, previous_sub_intent: str) -> IntentResult | None:
        if self.client is None:
            self.last_debug = {"status": "client_unavailable"}
            return None

        prompt = build_llm_intent_user_prompt(message, previous_sub_intent)
        parsed = self._classify_with_responses_api(prompt)
        if parsed is None:
            parsed = self._classify_with_chat_completions(prompt)

        if parsed is None:
            return None

        if parsed.confidence < self.config.confidence_threshold:
            return None

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
            self.last_debug = {
                "status": "responses_api_error",
                "error": repr(exc),
            }
            return None

        parsed = response.output_parsed
        if parsed is None:
            self.last_debug = {
                "status": "responses_api_empty",
                "raw": self._safe_dump(response),
            }
            return None

        self.last_debug = {
            "status": "responses_api_success",
            "raw": self._safe_dump(response),
        }
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
            self.last_debug = {
                "status": "chat_completions_error",
                "error": repr(exc),
            }
            return None

        content = response.choices[0].message.content if response.choices else None
        if not content:
            self.last_debug = {
                "status": "chat_completions_empty",
                "raw": self._safe_dump(response),
            }
            return None

        try:
            data = json.loads(content)
            parsed = LLMIntentDecision(**data)
            self.last_debug = {
                "status": "chat_completions_success",
                "raw": content,
            }
            return parsed
        except Exception as exc:
            self.last_debug = {
                "status": "chat_completions_parse_error",
                "error": repr(exc),
                "raw": content,
            }
            return None

    def _safe_dump(self, response: object) -> str:
        if hasattr(response, "model_dump_json"):
            try:
                return response.model_dump_json(indent=2)
            except Exception:
                pass
        return repr(response)
