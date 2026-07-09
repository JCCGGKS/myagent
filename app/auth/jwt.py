from __future__ import annotations

import datetime
from typing import Any

import jwt

from app.config import get_jwt_config


class JWTError(Exception):
    """JWT 校验失败（签名/过期/用途不匹配等）。"""


def _secret() -> str:
    return str(get_jwt_config().get("secret", "change-me-in-prod"))


def _algorithm() -> str:
    return str(get_jwt_config().get("algorithm", "HS256"))


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def create_access_token(user_id: str, username: str, email: str) -> str:
    """签发登录 token：携带必要用户信息，含有效期。"""
    expire_minutes = int(get_jwt_config().get("access_expire_minutes", 1440))
    payload: dict[str, Any] = {
        "sub": user_id,
        "user_id": user_id,
        "username": username,
        "email": email,
        "purpose": "access",
        "iat": _now(),
        "exp": _now() + datetime.timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def create_reset_token(user_id: str, email: str) -> str:
    """签发找回密码 token：短时效、purpose=reset，无状态校验。"""
    expire_minutes = int(get_jwt_config().get("reset_expire_minutes", 15))
    payload: dict[str, Any] = {
        "sub": user_id,
        "user_id": user_id,
        "email": email,
        "purpose": "reset",
        "iat": _now(),
        "exp": _now() + datetime.timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def decode_token(token: str, expected_purpose: str | None = None) -> dict[str, Any]:
    """解码并校验 token。

    Args:
        token: JWT 字符串。
        expected_purpose: 若提供，则要求 payload 的 purpose 与之匹配。

    Raises:
        JWTError: 签名错误、过期或用途不匹配。
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_algorithm()])
    except jwt.ExpiredSignatureError as exc:
        raise JWTError("token 已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise JWTError("token 无效") from exc

    if expected_purpose is not None and payload.get("purpose") != expected_purpose:
        raise JWTError("token 用途不匹配")
    return payload
