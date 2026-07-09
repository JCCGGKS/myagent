from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = ROOT_DIR / "logs"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    console: bool = True
    file: bool = True
    # 日志输出目录；目录下的日志文件统一按 yyyy-MM-dd 切分。
    dir_path: str = Field(default=str(DEFAULT_LOG_DIR))

    @property
    def numeric_level(self) -> int:
        return getattr(logging, self.level.upper(), logging.INFO)

    @property
    def log_dir(self) -> Path:
        return Path(self.dir_path)


def _daily_filename(prefix: str) -> str:
    """根据当前日期生成日志文件名：{prefix}-YYYY-MM-DD.log。"""
    return f"{prefix}-{datetime.now().strftime('%Y-%m-%d')}.log"


def setup_logging(config: LoggingConfig | None = None) -> None:
    """根据配置初始化 root logger：控制台 + 每日滚动的文件。"""
    if config is None:
        config = LoggingConfig()

    handlers: list[logging.Handler] = []

    if config.console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(_make_formatter())
        handlers.append(console_handler)

    if config.file:
        log_dir = config.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        # TimedRotatingFileHandler 在 midnight 切分；suffix 会自动追加。
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / _daily_filename("app"),
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=False,
        )
        file_handler.setFormatter(_make_formatter())
        handlers.append(file_handler)

    logging.basicConfig(
        level=config.numeric_level,
        handlers=handlers,
        force=True,
    )

    # 让各模块日志与 app 日志共用同一目录（按 yyyy-MM-dd 切分）。
    try:
        from app.utils.module_logger import configure_module_log_dir

        configure_module_log_dir(config.log_dir)
    except ImportError:
        # module_logger 尚未初始化（极端顺序问题），不阻断主流程。
        pass


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
