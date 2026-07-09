from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.pkgs.auth import JWTError, decode_token
from app.business.auth.models import UserInfo


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> UserInfo:
    """从 Authorization: Bearer <token> 解析当前用户。

    失败返回 401。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未提供认证 token")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token, expected_purpose="access")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return UserInfo(
        id=int(payload.get("user_id", 0)),
        username=str(payload.get("username", "")),
        email=str(payload.get("email", "")),
    )
