from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_mysql_config


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def _build_engine(cfg: dict[str, Any]):
    if not cfg.get("enabled", False):
        logger.warning("MySQL 未启用（mysql.enabled=false），认证相关接口将不可用。")
        return None
    url = (
        f"mysql+pymysql://{cfg.get('user', '')}:{cfg.get('password', '')}"
        f"@{cfg.get('host', 'localhost')}:{cfg.get('port', 3306)}/{cfg.get('database', '')}"
        f"?connect_timeout={cfg.get('connect_timeout', 10)}"
    )
    return create_engine(
        url,
        pool_size=cfg.get("pool_size", 5),
        pool_pre_ping=True,
        future=True,
    )


_MYSQL_CFG = get_mysql_config()
engine = _build_engine(_MYSQL_CFG)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False) if engine else None


def get_db_session():
    """FastAPI 依赖：提供数据库会话（DB 未启用时返回 None）。"""
    if SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
