from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils import load_yaml_file
from app.utils.config_paths import get_config_dir, get_app_env


CONFIG_DIR = get_config_dir()


def _env_name() -> str:
    """当前环境名：APP_ENV 为空时默认 'local'。"""
    return get_app_env()


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


def get_redis_config() -> dict[str, Any]:
    """返回 redis 配置段（图态 checkpointer 用）。

    与 mysql / qdrant 一致，统一从 ``llm_config.{env}.yml`` 读取，
    不再依赖 ``REDIS_URL`` 环境变量。含 ``enabled`` 开关：

    - ``enabled=false``（或段缺失）→ 后端回退 ``MemorySaver``（无 redis 依赖）；
    - ``enabled=true`` → 按 ``host`` / ``port`` / ``db`` / ``password`` 拼出
      ``redis://`` URL 交给 ``AsyncRedisSaver``。
    """
    cfg = _load_full_config().get("redis", {})
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "host": cfg.get("host", "127.0.0.1"),
        "port": int(cfg.get("port", 6379)),
        "db": int(cfg.get("db", 0)),
        "password": cfg.get("password", "") or "",
        "socket_timeout": float(cfg.get("socket_timeout", 5.0)),
    }


def get_jwt_config() -> dict[str, Any]:
    """返回 jwt 配置段。"""
    return _load_full_config().get("jwt", {})


def get_smtp_config() -> dict[str, Any]:
    """返回 smtp 配置段。"""
    return _load_full_config().get("smtp", {})
