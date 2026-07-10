from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils import load_yaml_file
from app.utils.config_paths import get_config_dir


DEFAULT_SCHEMA_PATH = get_config_dir() / "intent_schemas.yml"
DEFAULT_RULE_PATH = get_config_dir() / "intent_rules.yml"


class IntentSchemaRegistry:
    def __init__(self, schema_path: Path | None = None) -> None:
        self.schema_path = schema_path or DEFAULT_SCHEMA_PATH
        self._schemas = self._load()

    def get(self, main_intent: str) -> dict[str, Any]:
        return self._schemas.get(main_intent, self._schemas["unrecognize"])

    def _load(self) -> dict[str, dict[str, Any]]:
        data = load_yaml_file(self.schema_path)
        schemas = data.get("intent_schemas", {})
        if not isinstance(schemas, dict) or "unrecognize" not in schemas:
            raise ValueError(f"Invalid intent schema config: {self.schema_path}")
        return schemas


def get_intent_slot_schema(main_intent: str) -> dict[str, Any]:
    return IntentSchemaRegistry().get(main_intent)


class IntentRuleRegistry:
    def __init__(self, rule_path: Path | None = None) -> None:
        self.rule_path = rule_path or DEFAULT_RULE_PATH
        self._rules = self._load()

    def get(self) -> dict[str, Any]:
        return self._rules

    def get_routing_rules(self) -> list[dict[str, Any]]:
        return self._rules.get("routing_rules", [])

    def get_emotion_keywords(self) -> dict[str, list[str]]:
        return self._rules.get("emotion_keywords", {})

    def _load(self) -> dict[str, Any]:
        data = load_yaml_file(self.rule_path)
        routing_rules = data.get("routing_rules")
        if not isinstance(routing_rules, list):
            raise ValueError(f"intent_rules.yml 必须有 routing_rules 列表: {self.rule_path}")
        emotion_keywords = data.get("emotion_keywords", {})
        if not isinstance(emotion_keywords, dict):
            raise ValueError(f"intent_rules.yml 的 emotion_keywords 必须是 dict: {self.rule_path}")
        return {"routing_rules": routing_rules, "emotion_keywords": emotion_keywords}
