from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# 统一日志系统：所有模块共用一个 logger（name="myagent"），propagate=True 冒泡到
# root，由 logging_config 配置的单文件 logs/app-*.log 落盘 + 控制台输出。
#
# 刻意不再按模块拆分文件：单条请求会跨 api / auth / rag / agent / tool 多个模块，
# 拆分会让「一次请求」散落在多个文件里，无法顺序 grep 还原。统一落一个文件后，
# 再用消息里的 [tag]（[api] / [auth] / [rag] / [intent] / [tool] …）做分段检索。
_SHARED_LOGGER = logging.getLogger("myagent")
_SHARED_LOGGER.propagate = True


def _tagged(module: str, message: str) -> str:
    """把模块名折成消息前缀，形成 [tag] 分段，便于 grep。"""
    return f"[{module}] {message}"


def get_module_logger(module: str) -> logging.Logger:
    """兼容旧 API：返回共享 logger（忽略 module 的文件拆分语义）。"""
    return _SHARED_LOGGER


def configure_module_log_dir(dir_path: str | Path) -> None:  # noqa: D401
    """兼容旧 API：统一日志后不再需要按目录注册模块 logger，这里为无操作。"""
    return


# ---- 通用接口：自由文本 ----

def log_event(module: str, level: int, message: str, *args: Any) -> None:
    """以指定级别在共享日志里输出自由文本（带 [module] 前缀）。"""
    _SHARED_LOGGER.log(level, _tagged(module, message), *args)


def log_info(module: str, message: str, *args: Any) -> None:
    _SHARED_LOGGER.info(_tagged(module, message), *args)


def log_warning(module: str, message: str, *args: Any) -> None:
    _SHARED_LOGGER.warning(_tagged(module, message), *args)


def log_error(module: str, message: str, *args: Any) -> None:
    _SHARED_LOGGER.error(_tagged(module, message), *args)


# ---- 兼容旧 API（tool_logger）----

def configure_tool_log_dir(dir_path: str | Path) -> None:  # noqa: D401
    """兼容旧 API：等价于 configure_module_log_dir。"""
    configure_module_log_dir(dir_path)
