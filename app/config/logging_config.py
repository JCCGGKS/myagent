from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from pydantic import BaseModel, Field

from app.utils.trace import TraceIdFilter

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

    # trace_id 注入到每条日志：无请求上下文时为 '-'。挂在 handler 上，
    # 子 logger（graph / tool / api / auth / rag）冒泡上来的记录同样带上。
    trace_filter = TraceIdFilter()

    if config.console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(_make_formatter())
        console_handler.addFilter(trace_filter)
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
        file_handler.addFilter(trace_filter)
        handlers.append(file_handler)

    logging.basicConfig(
        level=config.numeric_level,
        handlers=handlers,
        force=True,
    )


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s [tid=%(trace_id)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
