from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.utils import load_json_file, load_yaml_file


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
        data = _load_config_file(path)
        return LLMConfig(**data)

    env_name = os.getenv("APP_ENV", DEFAULT_APP_ENV).strip().lower() or DEFAULT_APP_ENV
    base_config_path = CONFIG_DIR / f"llm_config.{env_name}.yml"
    local_override_path = CONFIG_DIR / "llm_config.local.yml"
    legacy_local_override_path = CONFIG_DIR / "llm_config.local.json"

    data: dict[str, object] = {}

    if base_config_path.exists():
        data.update(_load_config_file(base_config_path))

    if local_override_path.exists():
        data.update(_load_config_file(local_override_path))
    elif legacy_local_override_path.exists():
        data.update(_load_config_file(legacy_local_override_path))

    return LLMConfig(**data)


def _load_config_file(path: Path) -> dict[str, object]:
    if path.suffix == ".json":
        data = load_json_file(path)
        if not isinstance(data, dict):
            raise ValueError(f"JSON config must be a mapping: {path}")
        return data
    return load_yaml_file(path)
