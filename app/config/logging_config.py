from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from pydantic import BaseModel, Field

from app.utils.module_logger import TAGGED_MODULES
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
    """根据配置初始化日志：控制台 + 每个模块独立的每日滚动文件。

    每个模块（graph / intent / agent / tool / rag / response / context / api / auth）
    拥有自己的 logger（name="myagent.<module>"）与独立文件
    logs/<module>-YYYY-MM-DD.log；同时冒泡到 root 控制台，便于实时观察。
    单次请求跨多模块时，靠日志行里统一注入的 trace_id（[tid=...]）跨文件还原。
    """
    if config is None:
        config = LoggingConfig()

    # trace_id 注入到每条日志：无请求上下文时为 '-'。挂在 handler 上，
    # 各模块 logger 冒泡上来的记录同样带上。
    trace_filter = TraceIdFilter()
    formatter = _make_formatter()

    # root：仅承载控制台输出（不再落共享单文件）
    root = logging.getLogger()
    root.setLevel(config.numeric_level)
    root.handlers.clear()

    if config.console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(trace_filter)
        root.addHandler(console_handler)

    # 每个模块独立文件
    if config.file:
        log_dir = config.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        for module in TAGGED_MODULES:
            mlog = logging.getLogger(f"myagent.{module}")
            mlog.setLevel(config.numeric_level)
            mlog.handlers.clear()
            # TimedRotatingFileHandler 在 midnight 切分；suffix 会自动追加。
            file_handler = TimedRotatingFileHandler(
                filename=log_dir / _daily_filename(module),
                when="midnight",
                interval=1,
                backupCount=14,
                encoding="utf-8",
                utc=False,
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(trace_filter)
            mlog.addHandler(file_handler)
            # 仍冒泡到 root 控制台，避免模块日志只在文件、控制台看不到
            mlog.propagate = True


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s [tid=%(trace_id)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
