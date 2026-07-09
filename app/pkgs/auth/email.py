from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_smtp_config


logger = logging.getLogger(__name__)

RESET_LINK_TEMPLATE = "{base}/forgot?token={token}"


def send_reset_email(email: str, reset_token: str, base_url: str = "http://127.0.0.1:5173") -> None:
    """发送找回密码邮件。

    smtp 配置缺失 host 时直接报错（配置即启用）；enabled=false 时仅打印日志。
    """
    link = RESET_LINK_TEMPLATE.format(base=base_url, token=reset_token)
    cfg = get_smtp_config()

    if not cfg.get("enabled", False):
        logger.warning("SMTP 未启用，重置链接（仅本地）: %s -> %s", email, link)
        return

    if not cfg.get("host"):
        raise ValueError("SMTP 已启用但缺少 host 配置")

    msg = EmailMessage()
    msg["Subject"] = "找回密码 - 客服 Agent"
    msg["From"] = cfg.get("from_addr", "no-reply@myagent.local")
    msg["To"] = email
    msg.set_content(
        "我们收到了您的找回密码请求。请点击以下链接重置密码（15 分钟内有效）：\n\n"
        f"{link}\n\n若非本人操作，请忽略此邮件。"
    )

    with smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port", 465))) as server:
        server.login(cfg.get("user", ""), cfg.get("password", ""))
        server.send_message(msg)
