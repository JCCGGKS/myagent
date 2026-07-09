from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils import load_json_file
from app.utils.config_paths import get_config_dir


DATA_DIR = get_config_dir().parents[0] / "app" / "data"


def get_data_dir() -> Path:
    """返回 mock 资源目录（app/data）。"""
    return DATA_DIR


def _load_json_safe(filename: str) -> list[dict[str, Any]]:
    """容错读取 app/data 下的 JSON 数组；文件缺失/为空/格式错误均返回空列表。"""
    path = DATA_DIR / filename
    if not path.exists():
        return []
    try:
        data = load_json_file(path)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return []


def load_orders() -> list[dict[str, Any]]:
    return _load_json_safe("orders.json")


def load_logistics() -> list[dict[str, Any]]:
    return _load_json_safe("logistics.json")
