from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils import load_yaml_file


DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "intent_schemas.yml"
DEFAULT_RULE_PATH = Path(__file__).resolve().parents[2] / "config" / "intent_rules.yml"


class IntentSchemaRegistry:
    def __init__(self, schema_path: Path | None = None) -> None:
        self.schema_path = schema_path or DEFAULT_SCHEMA_PATH
        self._schemas = self._load()

    def get(self, main_intent: str) -> dict[str, Any]:
        return self._schemas.get(main_intent, self._schemas["unsupported"])

    def _load(self) -> dict[str, dict[str, Any]]:
        data = load_yaml_file(self.schema_path)
        schemas = data.get("intent_schemas", {})
        if not isinstance(schemas, dict) or "unsupported" not in schemas:
            raise ValueError(f"Invalid intent schema config: {self.schema_path}")
        return schemas


def get_intent_slot_schema(main_intent: str) -> dict[str, Any]:
    return IntentSchemaRegistry().get(main_intent)


class IntentRuleRegistry:
    def __init__(self, rule_path: Path | None = None) -> None:
        self.rule_path = rule_path or DEFAULT_RULE_PATH
        self._rules = self._load()

    def get(self) -> dict[str, list[str]]:
        return self._rules

    def _load(self) -> dict[str, list[str]]:
        data = load_yaml_file(self.rule_path)
        rules = data.get("intent_rules", {})
        if not isinstance(rules, dict):
            raise ValueError(f"Invalid intent rule config: {self.rule_path}")
        normalized: dict[str, list[str]] = {}
        for key, value in rules.items():
            if not isinstance(value, list):
                raise ValueError(f"Intent rule {key} must be a list: {self.rule_path}")
            normalized[key] = [str(item) for item in value]
        return normalized
