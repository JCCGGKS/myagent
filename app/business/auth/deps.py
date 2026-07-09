from __future__ import annotations

from fastapi import HTTPException, Request

from app.business.auth.models import UserInfo


def get_current_user(request: Request) -> UserInfo:
    """从 request.state.user 获取当前用户（由 AuthMiddleware 解析 token 后写入）。

    失败返回 401。
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未提供或无效的认证 token")
    return user
