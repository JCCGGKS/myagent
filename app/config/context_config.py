from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.utils import load_yaml_file
from app.utils.config_paths import get_config_dir, get_app_env


CONFIG_DIR = get_config_dir()


def _resolve_config_path() -> Path:
    """根据当前环境确定配置文件路径（与 rag_config 同约定）：llm_config.{env}.yml。"""
    env_name = get_app_env()
    return CONFIG_DIR / f"llm_config.{env_name}.yml"


class ContextConfig(BaseModel):
    # 上下文活动窗口大小：仅保留最近 N 条消息原样，窗口外折叠进 running_summary
    max_recent_messages: int = Field(default=6, ge=1)
    # running_summary 退化模式（无 LLM 折叠器）下的最大长度，避免无限增长
    max_summary_chars: int = Field(default=2000, ge=100)


class ContextConfigService:
    """上下文配置运行时持有服务（单例）。"""

    def __init__(self, config: ContextConfig | None = None) -> None:
        self._config = config or _load_context_config()

    def get_config(self) -> ContextConfig:
        return self._config


def _load_context_config() -> ContextConfig:
    """读取当前环境配置文件中的 `context` 段（无则回退到 pydantic 默认值）。"""
    path = _resolve_config_path()
    data: dict[str, object] = {}
    if path.exists():
        try:
            file_data = load_yaml_file(path)
        except Exception:
            file_data = {}
        if isinstance(file_data, dict):
            section = file_data.get("context")
            if isinstance(section, dict):
                data.update(section)
    return ContextConfig(**data)


# 模块级单例
_context_config_service = ContextConfigService()


def get_context_config_service() -> ContextConfigService:
    return _context_config_service
