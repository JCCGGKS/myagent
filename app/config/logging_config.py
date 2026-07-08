from __future__ import annotations

import logging
import sys
from pathlib import Path

from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LOG_FILE = ROOT_DIR / "logs" / "app.log"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    console: bool = True
    file: bool = True
    file_path: str = str(DEFAULT_LOG_FILE)

    @property
    def numeric_level(self) -> int:
        return getattr(logging, self.level.upper(), logging.INFO)


def setup_logging(config: LoggingConfig | None = None) -> None:
    if config is None:
        config = LoggingConfig()

    handlers: list[logging.Handler] = []

    if config.console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(_make_formatter())
        handlers.append(console_handler)

    if config.file:
        log_file = Path(config.file_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(_make_formatter())
        handlers.append(file_handler)

    logging.basicConfig(
        level=config.numeric_level,
        handlers=handlers,
        force=True,
    )


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
