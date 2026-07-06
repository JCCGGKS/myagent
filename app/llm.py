from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from app.config import LLMConfig
from app.models import IntentResult

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


class LLMIntentDecision(BaseModel):
    main_intent: Literal[
        "faq",
        "order_service",
        "logistics_service",
        "handoff_service",
        "chitchat",
        "unsupported",
    ]
    sub_intent: Literal[
        "faq.general",
        "order_service.query_status",
        "logistics_service.query_status",
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

        prompt = self._build_prompt(message, previous_sub_intent)
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
                    {"role": "system", "content": self._system_prompt()},
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
                    {"role": "system", "content": self._system_prompt()},
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

    def _system_prompt(self) -> str:
        return (
            "你是客服意图分类器。"
            "只能从给定的主意图和子意图中选择一个结果。"
            "如果用户表达不明确、超出当前系统能力，返回 unsupported.unknown。"
            "不要编造不存在的意图。"
            "输出必须是合法 JSON。"
        )

    def _build_prompt(self, message: str, previous_sub_intent: str) -> str:
        return f"""
请对下面的客服用户输入做意图分类，只能输出给定 schema。

可选主意图：
- faq
- order_service
- logistics_service
- handoff_service
- chitchat
- unsupported

可选子意图：
- faq.general
- order_service.query_status
- logistics_service.query_status
- handoff_service.request_human
- chitchat.greeting
- chitchat.thanks
- unsupported.unknown

判定原则：
- 问候类：你好、在吗、hello -> chitchat.greeting
- 感谢类：谢谢、辛苦了 -> chitchat.thanks
- 转人工类：要人工客服 -> handoff_service.request_human
- 订单状态类：查订单、发货了吗、订单状态 -> order_service.query_status
- 物流进度类：快递到哪了、物流更新、配送进度 -> logistics_service.query_status
- FAQ 类：标准知识问答，如发票怎么开、支持哪些支付方式、退款多久到账
- 其它未覆盖能力或无法稳定判断 -> unsupported.unknown

上一轮子意图：{previous_sub_intent}
当前用户输入：{message}
""".strip()

    def _safe_dump(self, response: object) -> str:
        if hasattr(response, "model_dump_json"):
            try:
                return response.model_dump_json(indent=2)
            except Exception:
                pass
        return repr(response)
