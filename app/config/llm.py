from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.config.logging_config import LoggingConfig, setup_logging
from app.utils import load_json_file, load_yaml_file
from app.utils.config_paths import get_config_dir, get_app_env


CONFIG_DIR = get_config_dir()
DEFAULT_APP_ENV = "test"


class LLMConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    model: str = "gpt-5.5"
    base_url: str | None = None
    timeout_seconds: float = 20.0
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    logging: LoggingConfig = LoggingConfig()

    @property
    def is_usable(self) -> bool:
        return self.enabled and bool(self.api_key.strip())


def _extract_config_sections(file_data: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    """从加载的 YAML/JSON 数据中分离 llm 和 logging 配置段。"""
    llm_data = file_data.get("llm", {})
    if not isinstance(llm_data, dict):
        llm_data = {}
    logging_data = file_data.get("logging", {})
    if not isinstance(logging_data, dict):
        logging_data = {}
    return llm_data, logging_data


def load_llm_config(path: Path | None = None) -> LLMConfig:
    if path is not None:
        if not path.exists():
            config = LLMConfig()
            setup_logging(config.logging)
            return config
        file_data = _load_config_file(path)
        llm_data, logging_data = _extract_config_sections(file_data)
        config = LLMConfig(**llm_data)
        config.logging = LoggingConfig(**logging_data)
        setup_logging(config.logging)
        return config

    env_name = os.getenv("APP_ENV", DEFAULT_APP_ENV).strip().lower() or get_app_env() or DEFAULT_APP_ENV
    base_config_path = CONFIG_DIR / f"llm_config.{env_name}.yml"
    local_override_path = CONFIG_DIR / "llm_config.local.yml"
    legacy_local_override_path = CONFIG_DIR / "llm_config.local.json"

    llm_data: dict[str, object] = {}
    logging_data: dict[str, object] = {}

    for config_path in [base_config_path, local_override_path]:
        if config_path.exists():
            file_data = _load_config_file(config_path)
            file_llm, file_logging = _extract_config_sections(file_data)
            llm_data.update(file_llm)
            logging_data.update(file_logging)

    if not local_override_path.exists() and legacy_local_override_path.exists():
        file_data = _load_config_file(legacy_local_override_path)
        file_llm, file_logging = _extract_config_sections(file_data)
        llm_data.update(file_llm)
        logging_data.update(file_logging)

    config = LLMConfig(**llm_data)
    config.logging = LoggingConfig(**logging_data)
    setup_logging(config.logging)
    return config


def _load_config_file(path: Path) -> dict[str, object]:
    if path.suffix == ".json":
        data = load_json_file(path)
        if not isinstance(data, dict):
            raise ValueError(f"JSON config must be a mapping: {path}")
        return data
    return load_yaml_file(path)
