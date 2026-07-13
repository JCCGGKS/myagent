from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.utils import load_yaml_file
from app.utils.config_paths import get_app_env, get_config_dir


logger = logging.getLogger(__name__)

CONFIG_DIR = get_config_dir()


def _resolve_config_path() -> Path:
    """checkpoint 配置与 rag / context 同约定，统一落到 llm_config.{env}.yml。"""
    env_name = get_app_env()
    return CONFIG_DIR / f"llm_config.{env_name}.yml"


class CheckpointConfig(BaseModel):
    # 图态快照（checkpointer）在 Redis 中的过期时间（秒）。
    # 0 表示不过期（禁用 TTL）；建议按「最大可接受对话间隔」设置。
    # 配置键以 CHECKPOINT_ 前缀标识，区别于其他 Redis TTL（如未来可能的缓存 TTL）。
    # 例如 604800 = 7 天：活跃会话每轮落库会刷新过期时间，仅长期空闲的会话才被回收。
    ttl_seconds: int = Field(default=604800, ge=0)


class CheckpointConfigService:
    """图态持久化（checkpoint）配置运行时持有服务（单例）。"""

    def __init__(self, config: CheckpointConfig | None = None) -> None:
        self._config = config or _load_checkpoint_config()

    def get_config(self) -> CheckpointConfig:
        return self._config


def _load_checkpoint_config() -> CheckpointConfig:
    """读取 checkpoint TTL 配置，优先级：环境变量 CHECKPOINT_TTL_SECONDS > 配置文件段。

    - 环境变量 ``CHECKPOINT_TTL_SECONDS``：运维快速覆盖，键名前缀指明这是图态快照的 TTL。
    - 配置文件 ``llm_config.{env}.yml`` 的 ``checkpoint`` 段：与 rag / context 同约定。
    两者皆无则回退到 pydantic 默认值（7 天）。
    """
    env_ttl = os.getenv("CHECKPOINT_TTL_SECONDS")
    if env_ttl is not None:
        try:
            return CheckpointConfig(ttl_seconds=int(env_ttl))
        except ValueError:
            logger.warning(
                "CHECKPOINT_TTL_SECONDS invalid (%r), falling back to config file / default",
                env_ttl,
            )

    path = _resolve_config_path()
    data: dict[str, object] = {}
    if path.exists():
        try:
            file_data = load_yaml_file(path)
        except Exception:
            file_data = {}
        if isinstance(file_data, dict):
            section = file_data.get("checkpoint")
            if isinstance(section, dict):
                data.update(section)
    return CheckpointConfig(**data)


# 模块级单例
_checkpoint_config_service = CheckpointConfigService()


def get_checkpoint_config_service() -> CheckpointConfigService:
    return _checkpoint_config_service
