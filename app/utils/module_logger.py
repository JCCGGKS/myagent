from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# 分模块日志系统：每个模块使用独立 logger（name="myagent.<module>"），
# 由 logging_config.setup_logging 为每个模块注册独立的每日滚动文件
# logs/<module>-YYYY-MM-DD.log + 控制台输出。
#
# 单条请求会跨 api / auth / rag / agent / tool 多个模块；按模块拆分文件后，
# 用日志行里统一注入的 trace_id（[tid=...]，见 TraceIdFilter）即可跨文件还原
# 同一次请求；模块内排查则直接看对应 logs/<module>-*.log。模块内仍保留
# [tag] 前缀（[api] / [auth] / [rag] / [intent] / [tool] …），便于在控制台/grep 时识别来源。
#
# 已知模块（setup_logging 会为这些名字注册独立文件 handler）：
TAGGED_MODULES = ("graph", "intent", "agent", "tool", "rag", "response", "context", "api", "auth")


def _module_logger_name(module: str) -> str:
    return f"myagent.{module}"


def _tagged(module: str, message: str) -> str:
    """把模块名折成消息前缀，形成 [tag] 分段，便于 grep。"""
    return f"[{module}] {message}"


def get_module_logger(module: str) -> logging.Logger:
    """返回指定模块的 logger（name="myagent.<module>"）。

    配合 logging_config.setup_logging 注册的独立文件 handler，该模块的日志会
    落入 logs/<module>-*.log 并同时冒泡到 root 控制台。
    """
    return logging.getLogger(_module_logger_name(module))


# 兼容旧 API（按目录注册模块 logger 已无意义，留作无操作）
def configure_module_log_dir(dir_path: str | Path) -> None:  # noqa: D401
    return


# ---- 通用接口：自由文本 ----

def log_event(module: str, level: int, message: str, *args: Any) -> None:
    """以指定级别在对应模块日志里输出自由文本（带 [module] 前缀）。"""
    get_module_logger(module).log(level, _tagged(module, message), *args)


def log_info(module: str, message: str, *args: Any) -> None:
    get_module_logger(module).info(_tagged(module, message), *args)


def log_warning(module: str, message: str, *args: Any) -> None:
    get_module_logger(module).warning(_tagged(module, message), *args)


def log_error(module: str, message: str, *args: Any) -> None:
    get_module_logger(module).error(_tagged(module, message), *args)


# ---- 兼容旧 API（tool_logger）----

def configure_tool_log_dir(dir_path: str | Path) -> None:  # noqa: D401
    """兼容旧 API：等价于 configure_module_log_dir。"""
    configure_module_log_dir(dir_path)
