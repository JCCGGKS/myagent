from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.utils import load_yaml_file


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


def _env_name() -> str:
    """当前环境名：APP_ENV 为空时默认 'local'。"""
    env = os.getenv("APP_ENV", "").strip().lower()
    if not env:
        env = "local"
    return env


def _config_path() -> Path:
    """当前环境对应的配置文件，统一为 llm_config.{env_name}.yml。"""
    return CONFIG_DIR / f"llm_config.{_env_name()}.yml"


def _load_full_config() -> dict[str, Any]:
    """读取当前环境配置文件，返回完整 dict（缺段时返回空字典）。"""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = load_yaml_file(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_mysql_config() -> dict[str, Any]:
    """返回 mysql 配置段（含 enabled 等字段）。"""
    return _load_full_config().get("mysql", {})


def get_jwt_config() -> dict[str, Any]:
    """返回 jwt 配置段。"""
    return _load_full_config().get("jwt", {})


def get_smtp_config() -> dict[str, Any]:
    """返回 smtp 配置段。"""
    return _load_full_config().get("smtp", {})
