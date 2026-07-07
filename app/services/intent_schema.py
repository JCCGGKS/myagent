from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils import load_yaml_file


DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "intent_schemas.yml"


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
