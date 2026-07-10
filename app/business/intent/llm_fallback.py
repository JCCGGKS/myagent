from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.config import LLMConfig
from app.schema import IntentResult
from app.schema.intent import (
    MAIN_INTENT_CODES,
    SUB_INTENT_CODES,
    MainIntentCode,
    SubIntentCode,
)
from app.business.prompts import LLM_INTENT_SYSTEM_PROMPT, build_llm_intent_user_prompt

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

logger = logging.getLogger(__name__)

# Valid values the router actually uses (derived from the single source of truth)
VALID_MAIN = set(MAIN_INTENT_CODES)
VALID_SUB = set(SUB_INTENT_CODES)


class LLMIntentDecision(BaseModel):
    model_config = {"populate_by_name": True}

    main_intent: MainIntentCode = "unrecognize"
    sub_intent: SubIntentCode = "unrecognize.unknown"

    confidence: float = 0.8
    needs_clarification: bool = False
    reason: str = ""

    # Qwen sometimes uses alternate field names; captured transiently by the
    # validator below and merged into main_intent/sub_intent, not stored.
    raw_intent: str | None = None
    raw_sub_intent: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, values: object) -> object:
        if isinstance(values, dict):
            # Qwen may return "intent" (dotted "main.sub") instead of main_intent/sub_intent
            if "intent" in values and "main_intent" not in values:
                intent_val = values.pop("intent")
                if isinstance(intent_val, str) and "." in intent_val:
                    values["main_intent"] = intent_val.split(".")[0]
                    values["sub_intent"] = intent_val
                elif isinstance(intent_val, str):
                    values["main_intent"] = intent_val

            # Qwen may return "intents" / "sub_intents" (plural)
            if "intents" in values:
                raw = values.pop("intents")
                if isinstance(raw, list) and raw:
                    values["main_intent"] = raw[0].split(".")[0] if "." in raw[0] else raw[0]
                    values["sub_intent"] = raw[0]
                elif isinstance(raw, str):
                    values["main_intent"] = raw.split(".")[0] if "." in raw else raw

            if "sub_intents" in values:
                raw = values.pop("sub_intents")
                if isinstance(raw, list) and raw:
                    values["sub_intent"] = raw[0]

            # Sanity-check: if main_intent is still not in VALID_MAIN, default
            if values.get("main_intent") not in VALID_MAIN:
                # try to salvage from sub_intent
                si = values.get("sub_intent", "")
                if isinstance(si, str) and "." in si:
                    values["main_intent"] = si.split(".")[0]
                else:
                    values["main_intent"] = "unrecognize"

            if values.get("sub_intent") not in VALID_SUB:
                mi = values.get("main_intent", "unrecognize")
                # guess a reasonable sub_intent
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
            logger.info("LLM fallback disabled: use_llm=False")
            return
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
        try:
            prompt = build_llm_intent_user_prompt(message, previous_sub_intent)
            parsed = self._classify_with_chat_completions(prompt)
        except Exception as exc:
            logger.warning("LLM fallback classify crashed: %s", repr(exc))
            return None

        if parsed is None:
            logger.info("LLM fallback: parsing failed, returning None")
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

    def _classify_with_chat_completions(self, prompt: str) -> LLMIntentDecision | None:
        """Call chat.completions and parse the JSON response."""
        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": LLM_INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
                stream=False,
            )
        except Exception as exc:
            logger.warning("chat.completions API error: %s", repr(exc))
            return None

        content = response.choices[0].message.content if response.choices else None
        if not content:
            logger.warning("chat.completions returned empty content")
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
            logger.warning("chat.completions JSON decode error: %s raw=%s", repr(exc), content[:200])
            return None

        # Normalize common Qwen field name variants
        normalized: dict[str, Any] = {}

        raw_main = (
            data.get("main_intent")
            or data.get("main_intent")
            or data.get("intent")
            or (data.get("intents")[0] if isinstance(data.get("intents"), list) and data["intents"] else None)
        )
        if isinstance(raw_main, str) and "." in raw_main:
            normalized["main_intent"] = raw_main.split(".")[0]
            normalized["sub_intent"] = raw_main
        elif isinstance(raw_main, str):
            normalized["main_intent"] = raw_main

        if "sub_intent" not in normalized:
            raw_sub = (
                data.get("sub_intent")
                or data.get("sub_intent")
                or data.get("intent")
                or (data.get("sub_intents")[0] if isinstance(data.get("sub_intents"), list) else None)
            )
            if isinstance(raw_sub, str):
                normalized["sub_intent"] = raw_sub

        if "main_intent" not in normalized:
            normalized["main_intent"] = "unrecognize"
        if "sub_intent" not in normalized:
            mi = normalized["main_intent"]
            guesses = {
                "order_query": "order_query.query_status",
                "logistics": "logistics.not_received",
                "after_sale_refund": "after_sale_refund.no_reason_return",
                "complaint": "complaint.service_complaint",
                "handoff_service": "handoff_service.request_human",
                "unrecognize": "unrecognize.unknown",
                "unsupported_biz": "unsupported_biz.out_of_scope",
            }
            normalized["sub_intent"] = guesses.get(mi, "unrecognize.unknown")

        raw_conf = data.get("confidence", data.get("confidence", 0.8))
        try:
            normalized["confidence"] = float(raw_conf)
        except (ValueError, TypeError):
            normalized["confidence"] = 0.8

        normalized["needs_clarification"] = bool(data.get("needs_clarification", False))
        normalized["reason"] = str(data.get("reason", ""))

        if normalized["main_intent"] not in VALID_MAIN:
            logger.warning("LLM returned invalid main_intent=%s, discarding", normalized["main_intent"])
            return None
        if normalized["sub_intent"] not in VALID_SUB:
            logger.warning("LLM returned invalid sub_intent=%s, discarding", normalized["sub_intent"])
            return None

        try:
            parsed = LLMIntentDecision(**normalized)
            logger.debug("chat.completions success: %s", content[:100])
            return parsed
        except Exception as exc:
            logger.warning("LLMIntentDecision construction error: %s normalized=%s", repr(exc), normalized)
            return None

    def _safe_dump(self, response: object) -> str:
        if hasattr(response, "model_dump_json"):
            try:
                return response.model_dump_json(indent=2)
            except Exception:
                pass
        return repr(response)
