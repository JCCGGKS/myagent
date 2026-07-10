from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from app.config.logging_config import DEFAULT_LOG_DIR

# 各模块的日志前缀。模块 → 文件前缀的映射。
# 增加模块时在此追加即可，应用启动时统一注册目录。
MODULE_LOG_PREFIXES: dict[str, str] = {
    "app": "app",
    "api": "api",
    "auth": "auth",
    "rag": "rag",
    "tool": "tool",
}

# 默认保留 14 天日志。
BACKUP_COUNT = 14

# 已创建的 logger 缓存，避免重复挂 handler。
_loggers: dict[str, logging.Logger] = {}
# 当前生效的日志目录（由 setup_logging 同步）。
_log_dir: Path = DEFAULT_LOG_DIR


def configure_module_log_dir(dir_path: str | Path) -> None:
    """切换所有模块日志目录；一般由 setup_logging 调用一次。"""
    global _log_dir
    _log_dir = Path(dir_path)
    _log_dir.mkdir(parents=True, exist_ok=True)
    # 清掉所有已建 logger 的 handler，让下次 get_module_logger 重建到新目录。
    for logger in _loggers.values():
        logger.handlers.clear()
    _loggers.clear()


def _daily_filename(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y-%m-%d')}.log"


def _build_handler(prefix: str) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        filename=_log_dir / _daily_filename(prefix),
        when="midnight",
        interval=1,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
        utc=False,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    return handler


def get_module_logger(module: str) -> logging.Logger:
    """获取（或创建）一个模块专用 logger。

    同一个模块名多次调用只创建一次；handler 列表不会重复挂。
    """
    if module in _loggers:
        return _loggers[module]

    prefix = MODULE_LOG_PREFIXES.get(module, module)
    logger_name = f"myagent.{module}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # 避免冒泡到 root 重复打印

    if not logger.handlers:
        _log_dir.mkdir(parents=True, exist_ok=True)
        logger.addHandler(_build_handler(prefix))

    _loggers[module] = logger
    return logger


# ---- 通用接口：自由文本 ----

def log_event(module: str, level: int, message: str, *args: Any) -> None:
    """以指定级别在指定模块日志里输出自由文本。"""
    get_module_logger(module).log(level, message, *args)


def log_info(module: str, message: str, *args: Any) -> None:
    get_module_logger(module).info(message, *args)


def log_warning(module: str, message: str, *args: Any) -> None:
    get_module_logger(module).warning(message, *args)


def log_error(module: str, message: str, *args: Any) -> None:
    get_module_logger(module).error(message, *args)


# ---- 兼容旧 API（tool_logger）----

def configure_tool_log_dir(dir_path: str | Path) -> None:  # noqa: D401
    """兼容旧 API：等价于 configure_module_log_dir。"""
    configure_module_log_dir(dir_path)
