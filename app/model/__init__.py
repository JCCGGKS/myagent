from __future__ import annotations

import logging
from typing import Any, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_mysql_config


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def _build_url(cfg: dict[str, Any], driver: str) -> str | None:
    """根据配置拼出数据库 URL；driver 决定同步/异步方言（如 mysql+pymysql / mysql+aiomysql）。"""
    if not cfg:
        return None
    missing = [k for k in ("host", "database", "user") if not cfg.get(k)]
    if missing:
        raise ValueError(f"MySQL 已配置但缺少必填字段：{missing}")

    return (
        f"{driver}://{cfg.get('user', '')}:{cfg.get('password', '')}"
        f"@{cfg.get('host', 'localhost')}:{cfg.get('port', 3306)}/{cfg.get('database', '')}"
        f"?connect_timeout={cfg.get('connect_timeout', 10)}"
    )


def _build_engine(cfg: dict[str, Any]) -> Any:
    """根据 mysql 配置构建（同步）engine。

    规则（用户口径：配置了就是启用）：
    - mysql 配置段缺失 → 返回 None（不启用，dao 用内存实现）。
    - 段存在但 host/database/user 等关键字段缺失 → 直接报错。
    - 段完整 → 建连；连不上由调用方（dao）在真正使用时抛错。
    """
    url = _build_url(cfg, "mysql+pymysql")
    if url is None:
        logger.info("MySQL 未配置（无 mysql 段），使用内存存储实现。")
        return None
    return create_engine(
        url,
        pool_size=cfg.get("pool_size", 5),
        pool_pre_ping=True,
        future=True,
    )


def _build_async_engine(cfg: dict[str, Any]) -> Any:
    """构建异步 engine（mysql+aiomysql）。无配置或驱动不可用时返回 None，回退同步/M1 行为。"""
    url = _build_url(cfg, "mysql+aiomysql")
    if url is None:
        return None
    try:
        return create_async_engine(
            url,
            pool_size=cfg.get("pool_size", 5),
            pool_pre_ping=True,
            future=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("异步 engine 构建失败，将回退同步 DAO（to_thread）：%r", exc)
        return None


_MYSQL_CFG = get_mysql_config()
engine = _build_engine(_MYSQL_CFG)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False) if engine else None

# M2：原生异步会话工厂。仅当配置了 mysql 且 aiomysql 可用时非 None；
# 否则为 None，dao 注入层（app/dao/__init__.py）回退到内存实现（进程内状态）。
AsyncSessionLocal = (
    async_sessionmaker(bind=_async_engine, expire_on_commit=False, class_=AsyncSession)
    if (_async_engine := _build_async_engine(_MYSQL_CFG)) is not None
    else None
)


def get_db_session() -> Iterator[Session]:
    """FastAPI 依赖：提供数据库会话（DB 未启用时返回 None）。"""
    if SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
