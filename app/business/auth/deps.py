from __future__ import annotations

from fastapi import HTTPException, Request

from app.schema.auth import UserInfo
from app.pkgs.auth import JWTError, decode_token


def get_current_user(request: Request) -> UserInfo:
    """从 request.state.user 获取当前用户（由 AuthMiddleware 解析 token 后写入）。

    失败返回 401。
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未提供或无效的认证 token")
    return user


def get_user_id_from_token(authorization: str | None) -> int | None:
    """从 Authorization Bearer token 中解析 int 类型的 user_id。"""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token, expected_purpose="access")
            user_id = payload.get("user_id")
            if user_id is not None:
                return int(user_id)
        except JWTError:
            pass
    return None


def resolve_user_id(
    request: Request,
    authorization: str | None = None,
) -> int:
    """解析当前请求的最终 user_id（int）。

    优先级：
    1. AuthMiddleware 解析 token 后写入的 request.state.user
    2. 手动传入的 Authorization Bearer token

    都获取不到时返回 401。不再回退请求体 user_id。
    """
    user = getattr(request.state, "user", None)
    if user is not None:
        return user.id

    token_uid = get_user_id_from_token(authorization)
    if token_uid is not None:
        return token_uid

    raise HTTPException(
        status_code=401,
        detail="Missing user_id (provide Authorization token)",
    )
