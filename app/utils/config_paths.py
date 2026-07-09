from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


def get_config_dir() -> Path:
    """返回项目配置目录（项目根/config）。"""
    return CONFIG_DIR


def get_app_env() -> str:
    """当前环境名：APP_ENV 为空时默认 'local'。"""
    env = os.getenv("APP_ENV", "").strip().lower()
    return env or "local"


def get_config_path(env_name: str | None = None) -> Path:
    """当前环境对应的配置文件路径：config/llm_config.{env}.yml。"""
    name = env_name or get_app_env()
    return CONFIG_DIR / f"llm_config.{name}.yml"
