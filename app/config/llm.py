from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DEFAULT_APP_ENV = "test"


class LLMConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    model: str = "gpt-5.5"
    base_url: str | None = None
    timeout_seconds: float = 20.0
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    fallback_on_unsupported_only: bool = True

    @property
    def is_usable(self) -> bool:
        return self.enabled and bool(self.api_key.strip())


def load_llm_config(path: Path | None = None) -> LLMConfig:
    if path is not None:
        if not path.exists():
            return LLMConfig()
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return LLMConfig(**data)

    env_name = os.getenv("APP_ENV", DEFAULT_APP_ENV).strip().lower() or DEFAULT_APP_ENV
    base_config_path = CONFIG_DIR / f"llm_config.{env_name}.json"
    local_override_path = CONFIG_DIR / "llm_config.local.json"

    data: dict[str, object] = {}

    if base_config_path.exists():
        with base_config_path.open("r", encoding="utf-8") as file:
            data.update(json.load(file))

    if local_override_path.exists():
        with local_override_path.open("r", encoding="utf-8") as file:
            data.update(json.load(file))

    return LLMConfig(**data)
