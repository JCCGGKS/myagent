from __future__ import annotations

import logging
from typing import Any, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_mysql_config


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def _build_engine(cfg: dict[str, Any]) -> Any:
    """根据 mysql 配置构建 engine。

    规则（用户口径：配置了就是启用）：
    - mysql 配置段缺失 → 返回 None（不启用，dao 用内存实现）。
    - 段存在但 host/database/user 等关键字段缺失 → 直接报错。
    - 段完整 → 建连；连不上由调用方（dao）在真正使用时抛错。
    """
    if not cfg:
        logger.info("MySQL 未配置（无 mysql 段），使用内存存储实现。")
        return None
    missing = [k for k in ("host", "database", "user") if not cfg.get(k)]
    if missing:
        raise ValueError(f"MySQL 已配置但缺少必填字段：{missing}")

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


def get_db_session() -> Iterator[Session]:
    """FastAPI 依赖：提供数据库会话（DB 未启用时返回 None）。"""
    if SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
